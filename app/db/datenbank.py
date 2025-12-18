import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DB_PATH = Path("data/index.db")


@dataclass
class DocumentMeta:
    source: str
    path: str
    filename: str
    extension: str
    size_bytes: int
    ctime: float
    mtime: float
    atime: Optional[float]
    owner: Optional[str]
    last_editor: Optional[str]
    msg_from: Optional[str] = None
    msg_to: Optional[str] = None
    msg_cc: Optional[str] = None
    msg_subject: Optional[str] = None
    msg_date: Optional[str] = None
    tags: Optional[str] = None
    content: str = ""
    title_or_subject: str = ""


@dataclass
class QuarantineEntry:
    doc_id: int
    source: str
    source_root: str
    original_path: str
    quarantine_path: str
    original_filename: str
    moved_at: str
    actor: str
    size_bytes: Optional[int] = None
    hash: Optional[str] = None
    status: str = "quarantined"
    restored_path: Optional[str] = None
    restored_at: Optional[str] = None
    hard_deleted_at: Optional[str] = None
    cleanup_deleted_at: Optional[str] = None


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                extension TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                ctime REAL NOT NULL,
                mtime REAL NOT NULL,
                atime REAL,
                owner TEXT,
                last_editor TEXT,
                msg_from TEXT,
                msg_to TEXT,
                msg_cc TEXT,
                msg_subject TEXT,
                msg_date TEXT,
                tags TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                doc_id UNINDEXED,
                content,
                title_or_subject,
                tokenize = 'unicode61 remove_diacritics 2'
            );

            CREATE TABLE IF NOT EXISTS index_runs (
                id INTEGER PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                scanned_files INTEGER DEFAULT 0,
                added INTEGER DEFAULT 0,
                updated INTEGER DEFAULT 0,
                removed INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                message TEXT
            );

            CREATE TABLE IF NOT EXISTS file_errors (
                id INTEGER PRIMARY KEY,
                run_id INTEGER,
                path TEXT NOT NULL,
                error_type TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES index_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS scanned_paths (
                run_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                PRIMARY KEY(run_id, path)
            );

            CREATE TABLE IF NOT EXISTS quarantine_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER,
                source TEXT NOT NULL,
                source_root TEXT NOT NULL,
                original_path TEXT NOT NULL,
                quarantine_path TEXT NOT NULL UNIQUE,
                original_filename TEXT NOT NULL,
                moved_at TEXT NOT NULL,
                actor TEXT NOT NULL,
                size_bytes INTEGER,
                hash TEXT,
                status TEXT NOT NULL DEFAULT 'quarantined',
                restored_path TEXT,
                restored_at TEXT,
                hard_deleted_at TEXT,
                cleanup_deleted_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_quarantine_status ON quarantine_entries(status);
            CREATE INDEX IF NOT EXISTS idx_quarantine_moved_at ON quarantine_entries(moved_at);
        """
        )


def upsert_document(conn: sqlite3.Connection, meta: DocumentMeta) -> int:
    cursor = conn.execute(
        """
        INSERT INTO documents (source, path, filename, extension, size_bytes, ctime, mtime, atime, owner, last_editor,
                               msg_from, msg_to, msg_cc, msg_subject, msg_date, tags)
        VALUES (:source, :path, :filename, :extension, :size_bytes, :ctime, :mtime, :atime, :owner, :last_editor,
                :msg_from, :msg_to, :msg_cc, :msg_subject, :msg_date, :tags)
        ON CONFLICT(path) DO UPDATE SET
            source=excluded.source,
            filename=excluded.filename,
            extension=excluded.extension,
            size_bytes=excluded.size_bytes,
            ctime=excluded.ctime,
            mtime=excluded.mtime,
            atime=excluded.atime,
            owner=excluded.owner,
            last_editor=excluded.last_editor,
            msg_from=excluded.msg_from,
            msg_to=excluded.msg_to,
            msg_cc=excluded.msg_cc,
            msg_subject=excluded.msg_subject,
            msg_date=excluded.msg_date,
            tags=excluded.tags
        RETURNING id;
        """,
        asdict(meta),
    )
    doc_id = cursor.fetchone()[0]
    conn.execute("DELETE FROM documents_fts WHERE doc_id = ?", (doc_id,))
    conn.execute(
        "INSERT INTO documents_fts (doc_id, content, title_or_subject) VALUES (?, ?, ?)",
        (doc_id, meta.content, meta.title_or_subject),
    )
    return doc_id


def remove_documents_by_paths(conn: sqlite3.Connection, missing_paths: Iterable[str]) -> int:
    paths = list(missing_paths)
    if not paths:
        return 0
    cursor = conn.execute(
        f"SELECT id FROM documents WHERE path IN ({','.join('?' * len(paths))})", paths
    )
    ids = [row[0] for row in cursor.fetchall()]
    if ids:
        conn.execute(f"DELETE FROM documents WHERE id IN ({','.join('?' * len(ids))})", ids)
        conn.execute(f"DELETE FROM documents_fts WHERE doc_id IN ({','.join('?' * len(ids))})", ids)
    return len(ids)


def remove_document_by_id(conn: sqlite3.Connection, doc_id: int) -> None:
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.execute("DELETE FROM documents_fts WHERE doc_id = ?", (doc_id,))


def search_documents(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 50,
    offset: int = 0,
    filters: Optional[Dict[str, Any]] = None,
    sort_key: Optional[str] = None,
    sort_dir: Optional[str] = None,
) -> List[sqlite3.Row]:
    if not query or not str(query).strip():
        return []
    filters = filters or {}
    where_clauses = []
    params: List[Any] = []
    sources_filter: List[str] = []
    if "source_labels" in filters:
        sources_filter = [s for s in filters["source_labels"] if s]
    elif "source" in filters and filters["source"]:
        sources_filter = [filters["source"]]
    if sources_filter:
        where_clauses.append(f"d.source IN ({','.join('?' * len(sources_filter))})")
        params.extend(sources_filter)
    if "extension" in filters:
        where_clauses.append("d.extension = ?")
        params.append(filters["extension"])
    if "time_filter" in filters:
        clause, value = _time_filter_clause(filters["time_filter"])
        if clause:
            where_clauses.append(clause)
            if isinstance(value, (tuple, list)):
                params.extend(value)
            else:
                params.append(value)

    where_sql = " AND ".join(where_clauses)
    if where_sql:
        where_sql = "AND " + where_sql

    order_by = "ORDER BY bm25(documents_fts)"
    if sort_key in {"filename", "source", "extension", "size_bytes", "mtime"}:
        direction = "DESC" if sort_dir == "desc" else "ASC"
        order_by = f"ORDER BY d.{sort_key} {direction}"

    if query.strip() == "*":
        order_by_nofts = order_by if order_by.startswith("ORDER BY d.") else "ORDER BY d.mtime DESC"
        cursor = conn.execute(
            f"""
            SELECT d.*, '' AS snippet
            FROM documents d
            WHERE 1=1
            {where_sql}
            {order_by_nofts}
            LIMIT ? OFFSET ?;
            """,
            [*params, limit, offset],
        )
    else:
        cursor = conn.execute(
            f"""
            SELECT d.*, snippet(documents_fts, 1, '<mark>', '</mark>', '...', 10) AS snippet
            FROM documents_fts
            JOIN documents d ON d.id = documents_fts.doc_id
            WHERE documents_fts MATCH ?
            {where_sql}
            {order_by}
            LIMIT ? OFFSET ?;
            """,
            [query, *params, limit, offset],
        )
    return cursor.fetchall()


def _time_filter_clause(key: str) -> Tuple[Optional[str], Optional[Any]]:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    key = key.lower()
    if key == "today":
        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        return "d.mtime >= ?", start.timestamp()
    if key == "yesterday":
        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - timedelta(days=1)
        end = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        return "(d.mtime >= ? AND d.mtime < ?)", (start.timestamp(), end.timestamp())
    if key == "last7":
        start = now - timedelta(days=7)
        return "d.mtime >= ?", start.timestamp()
    if key == "last30":
        start = now - timedelta(days=30)
        return "d.mtime >= ?", start.timestamp()
    if key == "last365":
        start = now - timedelta(days=365)
        return "d.mtime >= ?", start.timestamp()
    if key.isdigit() and len(key) == 4:
        year = int(key)
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        return "(d.mtime >= ? AND d.mtime < ?)", (start.timestamp(), end.timestamp())
    return None, None


def get_document(conn: sqlite3.Connection, doc_id: int) -> Optional[sqlite3.Row]:
    cursor = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
    row = cursor.fetchone()
    return row


def get_document_by_path(conn: sqlite3.Connection, path: str) -> Optional[sqlite3.Row]:
    cursor = conn.execute("SELECT * FROM documents WHERE path = ?", (path,))
    return cursor.fetchone()


def get_document_content(conn: sqlite3.Connection, doc_id: int) -> Optional[str]:
    cursor = conn.execute("SELECT content FROM documents_fts WHERE doc_id = ?", (doc_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def get_document_title(conn: sqlite3.Connection, doc_id: int) -> Optional[str]:
    cursor = conn.execute("SELECT title_or_subject FROM documents_fts WHERE doc_id = ?", (doc_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def update_document_metadata(
    conn: sqlite3.Connection,
    doc_id: int,
    *,
    path: Optional[str] = None,
    source: Optional[str] = None,
    filename: Optional[str] = None,
    extension: Optional[str] = None,
    size_bytes: Optional[int] = None,
    ctime: Optional[float] = None,
    mtime: Optional[float] = None,
    atime: Optional[float] = None,
    title_or_subject: Optional[str] = None,
) -> bool:
    cols = []
    params: List[Any] = []
    if path is not None:
        cols.append("path = ?")
        params.append(path)
    if source is not None:
        cols.append("source = ?")
        params.append(source)
    if filename is not None:
        cols.append("filename = ?")
        params.append(filename)
    if extension is not None:
        cols.append("extension = ?")
        params.append(extension)
    if size_bytes is not None:
        cols.append("size_bytes = ?")
        params.append(size_bytes)
    if ctime is not None:
        cols.append("ctime = ?")
        params.append(ctime)
    if mtime is not None:
        cols.append("mtime = ?")
        params.append(mtime)
    if atime is not None:
        cols.append("atime = ?")
        params.append(atime)

    if cols:
        result = conn.execute(f"UPDATE documents SET {', '.join(cols)} WHERE id = ?", (*params, doc_id))
        if result.rowcount == 0:
            return False

    if title_or_subject is not None:
        conn.execute("UPDATE documents_fts SET title_or_subject = ? WHERE doc_id = ?", (title_or_subject, doc_id))

    return bool(cols or title_or_subject is not None)


def insert_quarantine_entry(conn: sqlite3.Connection, entry: QuarantineEntry) -> int:
    payload = asdict(entry)
    cur = conn.execute(
        """
        INSERT INTO quarantine_entries (
            doc_id, source, source_root, original_path, quarantine_path, original_filename, moved_at, actor,
            size_bytes, hash, status, restored_path, restored_at, hard_deleted_at, cleanup_deleted_at
        ) VALUES (
            :doc_id, :source, :source_root, :original_path, :quarantine_path, :original_filename, :moved_at, :actor,
            :size_bytes, :hash, :status, :restored_path, :restored_at, :hard_deleted_at, :cleanup_deleted_at
        );
        """,
        payload,
    )
    return cur.lastrowid


def get_quarantine_entry(conn: sqlite3.Connection, entry_id: int) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM quarantine_entries WHERE id = ?", (entry_id,))
    return cur.fetchone()


def get_quarantine_entry_by_path(conn: sqlite3.Connection, quarantine_path: str) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM quarantine_entries WHERE quarantine_path = ?", (quarantine_path,))
    return cur.fetchone()


def list_quarantine_entries(
    conn: sqlite3.Connection, status: Optional[str] = None, source: Optional[str] = None
) -> List[sqlite3.Row]:
    sql = "SELECT * FROM quarantine_entries"
    params: List[Any] = []
    clauses: List[str] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY moved_at DESC, id DESC"
    cur = conn.execute(sql, params)
    return cur.fetchall()


def update_quarantine_entry(conn: sqlite3.Connection, entry_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = []
    params: List[Any] = []
    for key, value in fields.items():
        cols.append(f"{key} = ?")
        params.append(value)
    params.append(entry_id)
    conn.execute(f"UPDATE quarantine_entries SET {', '.join(cols)} WHERE id = ?", params)


def mark_quarantine_restored(
    conn: sqlite3.Connection, entry_id: int, restored_path: str, restored_at: str
) -> None:
    update_quarantine_entry(
        conn,
        entry_id,
        status="restored",
        restored_path=restored_path,
        restored_at=restored_at,
    )


def mark_quarantine_hard_deleted(conn: sqlite3.Connection, entry_id: int, deleted_at: str) -> None:
    update_quarantine_entry(
        conn,
        entry_id,
        status="hard_deleted",
        hard_deleted_at=deleted_at,
    )


def mark_quarantine_cleanup_deleted(conn: sqlite3.Connection, entry_id: int, deleted_at: str) -> None:
    update_quarantine_entry(
        conn,
        entry_id,
        status="cleanup_deleted",
        cleanup_deleted_at=deleted_at,
    )


def record_index_run_start(
    conn: sqlite3.Connection, started_at: str, status: str = "running"
) -> int:
    cur = conn.execute(
        "INSERT INTO index_runs (started_at, status) VALUES (?, ?)", (started_at, status)
    )
    return cur.lastrowid


def record_index_run_finish(
    conn: sqlite3.Connection,
    run_id: int,
    finished_at: str,
    status: str,
    scanned_files: int,
    added: int,
    updated: int,
    removed: int,
    errors: int,
    message: Optional[str] = None,
) -> None:
    conn.execute(
        """
        UPDATE index_runs
        SET finished_at=?, status=?, scanned_files=?, added=?, updated=?, removed=?, errors=?, message=?
        WHERE id=?
        """,
        (finished_at, status, scanned_files, added, updated, removed, errors, message, run_id),
    )


def record_file_error(
    conn: sqlite3.Connection, run_id: int, path: str, error_type: str, message: str, created_at: str
) -> None:
    conn.execute(
        """
        INSERT INTO file_errors (run_id, path, error_type, message, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, path, error_type, message, created_at),
    )


def get_status(conn: sqlite3.Connection) -> Dict[str, Any]:
    total_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    last_run = conn.execute(
        "SELECT * FROM index_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    recent_runs = conn.execute(
        "SELECT * FROM index_runs ORDER BY started_at DESC LIMIT 10"
    ).fetchall()
    ext_counts = conn.execute("SELECT extension, COUNT(*) AS c FROM documents GROUP BY extension").fetchall()
    return {"total_docs": total_docs, "last_run": last_run, "recent_runs": recent_runs, "ext_counts": ext_counts}


def list_paths_by_sources(conn: sqlite3.Connection, sources: List[str]) -> List[str]:
    if not sources:
        return []
    cursor = conn.execute(
        f"SELECT path FROM documents WHERE source IN ({','.join('?' * len(sources))})",
        sources,
    )
    return [row[0] for row in cursor.fetchall()]


def count_documents_by_source(conn: sqlite3.Connection, sources: List[str]) -> Dict[str, int]:
    if not sources:
        return {}
    placeholders = ",".join("?" * len(sources))
    cursor = conn.execute(
        f"SELECT source, COUNT(*) FROM documents WHERE source IN ({placeholders}) GROUP BY source",
        sources,
    )
    return {row[0]: row[1] for row in cursor.fetchall()}


def get_sample_paths_by_source(conn: sqlite3.Connection, sources: List[str]) -> Dict[str, str]:
    if not sources:
        return {}
    result: Dict[str, str] = {}
    for src in sources:
        cur = conn.execute("SELECT path FROM documents WHERE source = ? LIMIT 1", (src,))
        row = cur.fetchone()
        if row and row[0]:
            result[src] = row[0]
    return result


def add_scanned_path(conn: sqlite3.Connection, run_id: int, path: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO scanned_paths (run_id, path) VALUES (?, ?)",
        (run_id, path),
    )


def reset_scanned_paths(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute("DELETE FROM scanned_paths WHERE run_id = ?", (run_id,))


def remove_documents_not_scanned(conn: sqlite3.Connection, run_id: int, sources: List[str]) -> int:
    if not sources:
        return 0
    placeholders = ",".join("?" * len(sources))
    cursor = conn.execute(
        f"""
        SELECT id FROM documents
        WHERE source IN ({placeholders})
        AND path NOT IN (SELECT path FROM scanned_paths WHERE run_id = ?)
        """,
        [*sources, run_id],
    )
    ids = [row[0] for row in cursor.fetchall()]
    if ids:
        conn.execute(f"DELETE FROM documents WHERE id IN ({','.join('?' * len(ids))})", ids)
        conn.execute(f"DELETE FROM documents_fts WHERE doc_id IN ({','.join('?' * len(ids))})", ids)
    return len(ids)


def cleanup_scanned_paths(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute("DELETE FROM scanned_paths WHERE run_id = ?", (run_id,))


def list_errors(conn: sqlite3.Connection, limit: int = 50, offset: int = 0) -> List[sqlite3.Row]:
    cursor = conn.execute(
        """
        SELECT * FROM file_errors
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )
    return cursor.fetchall()


def get_last_run(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    cursor = conn.execute(
        """
        SELECT * FROM index_runs ORDER BY started_at DESC LIMIT 1
        """
    )
    return cursor.fetchone()


def error_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM file_errors").fetchone()[0]


def list_existing_meta(conn: sqlite3.Connection) -> Dict[str, Tuple[float, float]]:
    cursor = conn.execute("SELECT path, size_bytes, mtime FROM documents")
    return {row["path"]: (row["size_bytes"], row["mtime"]) for row in cursor.fetchall()}


def delete_documents_by_source(conn: sqlite3.Connection, sources: List[str]) -> int:
    if not sources:
        return 0
    placeholders = ",".join("?" * len(sources))
    cursor = conn.execute(f"SELECT id FROM documents WHERE source IN ({placeholders})", sources)
    ids = [row[0] for row in cursor.fetchall()]
    if ids:
        conn.execute(f"DELETE FROM documents WHERE id IN ({','.join('?' * len(ids))})", ids)
        conn.execute(f"DELETE FROM documents_fts WHERE doc_id IN ({','.join('?' * len(ids))})", ids)
    return len(ids)
