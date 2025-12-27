import concurrent.futures
import json
import logging
import os
import time
import warnings
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple
import queue
import threading
from logging.handlers import RotatingFileHandler

from app.config_loader import CentralConfig
from app import config_db
from app.db import datenbank as db
from app.db.datenbank import DocumentMeta
from app.indexer import extractors
from app.services import readiness
from app import reporting

logger = logging.getLogger("indexer")

stop_event = threading.Event()


SUPPORTED_EXTENSIONS = {".pdf", ".rtf", ".msg", ".txt", ".eml"}
RUN_STATUS_FILE = Path("data/index.run")
HEARTBEAT_FILE = Path("data/index.heartbeat")
LIVE_STATUS_FILE = Path("data/index.live.json")
LIVE_STATUS_LOCK = threading.Lock()
live_status: Optional["LiveStatus"] = None
WARN_CONTEXT = threading.local()
LOG_BUFFER_MAX = 2000
LOG_BUFFER: Deque[Tuple[int, str]] = deque()
LOG_SEQ = 0


def _should_ignore_error(error_type: str, message: str) -> bool:
    msg = (message or "").lower()
    if error_type in {"PdfReadError", "PdfStreamError"}:
        if any(kw in msg for kw in ["password", "encrypted", "decrypt", "verschlüsselt"]):
            return True
        if "xref table read error" in msg or "stream has ended unexpectedly" in msg:
            return True
        if "ei stream not found" in msg:
            return True
    if error_type == "FileNotDecryptedError":
        return True
    if error_type == "UnicodeDecodeError":
        if "cp950" in msg or "illegal multibyte" in msg:
            return True
    if error_type == "EmptyFileError" or "cannot read an empty file" in msg:
        return True
    if error_type == "RecursionError":
        return True
    return False


def _get_base_root(env_default: str = "/data") -> Path:
    raw = os.getenv("DATA_CONTAINER_PATH")
    if raw:
        return Path(raw).resolve()
    try:
        return Path(config_db.get_setting("base_data_root", env_default) or env_default).resolve()
    except Exception:
        return Path(env_default).resolve()


def validate_root_entries(root_entries: Iterable[tuple[Path, str, str]], base_root: Optional[Path] = None) -> List[tuple[Path, str, str]]:
    base = (base_root or _get_base_root()).resolve()
    if str(base) in {"", "/"}:
        raise ValueError("Ungültiger Basis-Pfad für Daten (DATA_CONTAINER_PATH)")
    if not base.exists() or not base.is_dir():
        raise ValueError(f"Basis-Ordner nicht gefunden: {base}")
    validated: List[tuple[Path, str, str]] = []
    for raw_root, label, type_ in root_entries:
        root = Path(raw_root).resolve()
        if str(root) in {"", "/"}:
            raise ValueError("Ungültiger Wurzelpfad")
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Wurzelpfad nicht gefunden: {root}")
        try:
            root.relative_to(base)
        except ValueError:
            raise ValueError(f"Wurzelpfad {root} liegt nicht unter Basis {base}")
        validated.append((root, label, type_ or "file"))
    return validated


@dataclass
class LiveStatus:
    run_id: int
    started_at: str
    started_ts: float
    status: str
    total_files: int
    scanned: int
    added: int
    updated: int
    removed: int
    errors: int
    skipped: int
    current_path: Optional[str] = None
    message: Optional[str] = None
    finished_at: Optional[str] = None
    heartbeat: int = 0

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["elapsed_seconds"] = max(0, int(time.time() - self.started_ts))
        return data


class LiveBufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            return
        if not msg.endswith("\n"):
            msg += "\n"
        push_log_line(msg)


def push_log_line(line: str) -> None:
    global LOG_SEQ
    LOG_SEQ += 1
    LOG_BUFFER.append((LOG_SEQ, line))
    while len(LOG_BUFFER) > LOG_BUFFER_MAX:
        LOG_BUFFER.popleft()


def get_log_tail(limit: int = 200) -> Dict[str, Any]:
    limit = max(1, min(limit, LOG_BUFFER_MAX))
    items = list(LOG_BUFFER)[-limit:]
    lines = [line for _, line in items]
    start_seq = items[0][0] if items else 0
    total = LOG_SEQ
    return {"lines": lines, "from": start_seq - 1 if start_seq else 0, "total": total}


def get_log_since(seq: int, limit: int = 500) -> Dict[str, Any]:
    limit = max(1, min(limit, LOG_BUFFER_MAX))
    items = [item for item in LOG_BUFFER if item[0] > seq]
    items = items[:limit]
    lines = [line for _, line in items]
    start_seq = items[0][0] if items else seq
    total = LOG_SEQ
    return {"lines": lines, "from": start_seq - 1 if items else seq, "total": total}


def setup_logging(config: CentralConfig) -> None:
    log_dir = config.logging.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "indexer.log"
    try:
        log_file.touch(exist_ok=True)
    except Exception:
        pass
    level = getattr(logging, config.logging.level, logging.INFO)
    idx_logger = logging.getLogger("indexer")
    idx_logger.setLevel(level)
    idx_logger.propagate = False
    # replace handlers to avoid duplicates and to ignore prior basicConfig
    for h in list(idx_logger.handlers):
        idx_logger.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=3)
    file_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    buffer_handler = LiveBufferHandler()
    buffer_handler.setFormatter(fmt)

    for handler in (file_handler, stream_handler, buffer_handler):
        idx_logger.addHandler(handler)

    # capture warnings and third-party logs into the same file
    logging.captureWarnings(True)
    warn_logger = logging.getLogger("py.warnings")
    warn_logger.setLevel(level)
    warn_logger.propagate = False
    for h in list(warn_logger.handlers):
        warn_logger.removeHandler(h)
    for handler in (file_handler, buffer_handler):
        warn_logger.addHandler(handler)
    root = logging.getLogger()
    if file_handler not in root.handlers:
        root.addHandler(file_handler)
    def showwarning(message, category, filename, lineno, file=None, line=None):
        path = getattr(WARN_CONTEXT, "path", None)
        base = Path(path or filename)
        logger.warning("%s %s %s", category.__name__, base, base.name)
    warnings.showwarning = showwarning


def _persist_live_status(snapshot: LiveStatus) -> None:
    try:
        LIVE_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        LIVE_STATUS_FILE.write_text(json.dumps(snapshot.to_dict()), encoding="utf-8")
    except Exception:
        pass


def init_live_status(run_id: int, start_time: str, total_files: int) -> None:
    global live_status
    now_ts = time.time()
    with LIVE_STATUS_LOCK:
        live_status = LiveStatus(
            run_id=run_id,
            started_at=start_time,
            started_ts=now_ts,
            status="running",
            total_files=total_files,
            scanned=0,
            added=0,
            updated=0,
            removed=0,
            errors=0,
            skipped=0,
            heartbeat=int(now_ts),
        )
        snapshot = live_status
    _persist_live_status(snapshot)


def update_live_status(
    counters: Dict[str, int],
    current_path: Optional[str] = None,
    status: Optional[str] = None,
    message: Optional[str] = None,
    finished: bool = False,
    total_files: Optional[int] = None,
) -> None:
    global live_status
    now_ts = time.time()
    snapshot = None
    with LIVE_STATUS_LOCK:
        if live_status is None:
            return
        live_status.scanned = counters.get("scanned", live_status.scanned)
        live_status.added = counters.get("added", live_status.added)
        live_status.updated = counters.get("updated", live_status.updated)
        live_status.removed = counters.get("removed", live_status.removed)
        live_status.errors = counters.get("errors", live_status.errors)
        live_status.skipped = counters.get("skipped", live_status.skipped)
        if total_files is not None:
            live_status.total_files = total_files
        if current_path is not None:
            live_status.current_path = current_path
        if status:
            live_status.status = status
        if message is not None:
            live_status.message = message
        if finished and not live_status.finished_at:
            live_status.finished_at = datetime.now(timezone.utc).isoformat()
        live_status.heartbeat = int(now_ts)
        snapshot = live_status
    if snapshot:
        _persist_live_status(snapshot)
        touch_heartbeat()


def get_live_status() -> Optional[Dict[str, Any]]:
    with LIVE_STATUS_LOCK:
        if live_status:
            return live_status.to_dict()
    if LIVE_STATUS_FILE.exists():
        try:
            data = json.loads(LIVE_STATUS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            return None
    return None


def run_index_lauf(config: CentralConfig) -> Dict[str, int]:
    stop_event.clear()
    db.init_db()
    setup_logging(config)
    touch_heartbeat()

    start_time = datetime.now(timezone.utc).isoformat()
    counters = {"scanned": 0, "added": 0, "updated": 0, "removed": 0, "errors": 0, "skipped": 0}
    finish_message: Optional[str] = None
    status_override: Optional[str] = None
    existing_counts: Dict[str, int] = {}

    with db.get_conn() as conn:
        run_id = db.record_index_run_start(conn, start_time)
        db.reset_scanned_paths(conn, run_id)
        save_run_id(run_id)

    normalized_roots: List[tuple[Path, str, str]] = []
    for entry in config.paths.roots:
        try:
            root, label, type_val = entry
        except Exception:
            root, label = entry
            type_val = "file"
        normalized_roots.append((Path(root), label, type_val or "file"))
    root_entries = validate_root_entries(normalized_roots)
    sample_paths: Dict[str, str] = {}
    maildir_entries: List[tuple[Path, str]] = [(root, label) for root, label, type_ in root_entries if (type_ or "file") == "maildir"]
    file_entries: List[tuple[Path, str]] = [(root, label) for root, label, type_ in root_entries if (type_ or "file") == "file"]

    combined_labels = [label for _, label, _ in root_entries]
    try:
        with db.get_conn() as conn:
            existing_counts = db.count_documents_by_source(conn, combined_labels)
            sample_paths = db.get_sample_paths_by_source(conn, combined_labels)
    except Exception:
        existing_counts = {}
        sample_paths = {}
    readiness_result = readiness.check_sources_ready(file_entries + maildir_entries, existing_counts, sample_paths)
    if not readiness_result.ok:
        finish_message = readiness_result.message or "Netzlaufwerk nicht bereit"
        logger.warning("Indexlauf #%s abgebrochen: %s", run_id, finish_message)
        init_live_status(run_id, start_time, 0)
        update_live_status(counters, status="error", message=finish_message, finished=True)
        with db.get_conn() as conn:
            db.record_index_run_finish(
                conn,
                run_id,
                datetime.now(timezone.utc).isoformat(),
                "error",
                0,
                0,
                0,
                0,
                0,
                finish_message,
            )
        clear_run_id()
        return counters
    if not root_entries:
        logger.warning("Keine roots konfiguriert, Indexlauf beendet")
        init_live_status(run_id, start_time, 0)
        update_live_status(counters, status="completed", message="keine Wurzelpfade konfiguriert", finished=True)
        with db.get_conn() as conn:
            db.record_index_run_finish(
                conn,
                run_id,
                datetime.now(timezone.utc).isoformat(),
                "completed",
                0,
                0,
                0,
                0,
                0,
                "keine Wurzelpfade konfiguriert",
            )
        return counters

    total_files = 0
    logger.info("Indexlauf #%s gestartet, Roots: %s", run_id, ", ".join([str(r[0]) for r in root_entries]))
    init_live_status(run_id, start_time, total_files)

    work_queue: "queue.Queue[Optional[Dict]]" = queue.Queue(maxsize=200)
    last_status_write = 0.0

    def flush_live_status(current_path: Optional[str] = None, force: bool = False) -> None:
        nonlocal last_status_write
        now_ts = time.time()
        if force or now_ts - last_status_write >= 0.5:
            status_value = "stopping" if stop_event.is_set() else None
            update_live_status(counters, current_path=current_path, status=status_value)
            last_status_write = now_ts

    def writer():
        conn = db.connect()
        try:
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA temp_store=MEMORY;")
            processed = 0
            while True:
                item = work_queue.get()
                if item is None:
                    break
                kind = item.get("type")
                path_str = item.get("path") if item else None
                if kind == "error":
                    counters["scanned"] += 1
                    counters["skipped"] += 1
                    if path_str:
                        db.add_scanned_path(conn, run_id, path_str)
                    ignored = _should_ignore_error(item.get("error_type") or "", item.get("message") or "")
                    try:
                        db.record_file_error(
                            conn,
                            run_id=run_id,
                            path=path_str or "",
                            error_type=item["error_type"],
                            message=item["message"],
                            created_at=datetime.now(timezone.utc).isoformat(),
                            ignored=ignored,
                        )
                    finally:
                        if not ignored:
                            counters["errors"] += 1
                elif kind == "unchanged":
                    counters["scanned"] += 1
                    counters["skipped"] += 1
                    if path_str:
                        db.add_scanned_path(conn, run_id, path_str)
                elif kind == "document":
                    meta: DocumentMeta = item["meta"]
                    counters["scanned"] += 1
                    if meta.path:
                        db.add_scanned_path(conn, run_id, meta.path)
                    try:
                        db.upsert_document(conn, meta)
                        if item.get("existing"):
                            counters["updated"] += 1
                            db.record_index_event(conn, run_id, "updated", meta.path, meta.source, actor="indexer")
                        else:
                            counters["added"] += 1
                            db.record_index_event(conn, run_id, "added", meta.path, meta.source, actor="indexer")
                    except Exception as exc:
                        ignored = _should_ignore_error(type(exc).__name__, str(exc))
                        try:
                            db.record_file_error(
                                conn,
                                run_id=run_id,
                                path=meta.path,
                                error_type=type(exc).__name__,
                                message=str(exc),
                                created_at=datetime.now(timezone.utc).isoformat(),
                                ignored=ignored,
                            )
                        finally:
                            if not ignored:
                                counters["errors"] += 1
                        # Attempt to reopen connection if broken
                        try:
                            conn.close()
                        except Exception:
                            pass
                        conn = db.connect()
                        conn.execute("PRAGMA synchronous=NORMAL;")
                        conn.execute("PRAGMA temp_store=MEMORY;")
                work_queue.task_done()
                try:
                    conn.commit()
                except Exception:
                    pass
                flush_live_status(path_str if path_str else None)
        finally:
            conn.close()

    writer_thread = threading.Thread(target=writer, daemon=True)
    writer_thread.start()

    thread_local = threading.local()

    def get_thread_conn():
        conn = getattr(thread_local, "conn", None)
        if conn is None:
            conn = db.connect()
            conn.execute("PRAGMA query_only=1;")
            thread_local.conn = conn
        return conn

    def process_file_task(real_path: Path, original_path: Path, source: str) -> None:
        if stop_event.is_set():
            return
        try:
            stat = real_path.stat()
        except FileNotFoundError:
            work_queue.put({"type": "error", "path": str(original_path), "error_type": "FileNotFound", "message": "not found"})
            return

        max_size = config.indexer.max_file_size_mb
        if max_size and stat.st_size > max_size * 1024 * 1024:
            work_queue.put({"type": "unchanged", "path": str(original_path)})
            return

        ext = real_path.suffix.lower()
        meta = DocumentMeta(
            source=source,
            path=str(original_path),
            filename=original_path.name,
            extension=ext,
            size_bytes=stat.st_size,
            ctime=stat.st_ctime,
            mtime=stat.st_mtime,
            atime=stat.st_atime if hasattr(stat, "st_atime") else None,
            owner=get_owner(stat),
            last_editor=get_owner(stat),
        )
        try:
            conn = get_thread_conn()
            cur = conn.execute("SELECT size_bytes, mtime FROM documents WHERE path = ?", (str(original_path),))
            existing_row = cur.fetchone()
            if existing_row and existing_row[0] == meta.size_bytes and existing_row[1] == meta.mtime:
                work_queue.put({"type": "unchanged", "path": str(original_path)})
                return
            meta_existing = bool(existing_row)
        except Exception:
            meta_existing = False

        try:
            WARN_CONTEXT.path = str(original_path)
            fill_content(meta, real_path, ext)
            if stop_event.is_set():
                return
            work_queue.put({"type": "document", "meta": meta, "existing": meta_existing})
        except Exception as exc:
            logger.error("%s %s %s", type(exc).__name__, original_path, original_path.name)
            work_queue.put(
                {
                    "type": "error",
                    "path": str(original_path),
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        finally:
            WARN_CONTEXT.path = None
            touch_heartbeat()

    def process_mail_task(real_path: Path, source: str) -> None:
        if stop_event.is_set():
            return
        try:
            stat = real_path.stat()
        except FileNotFoundError:
            work_queue.put({"type": "error", "path": str(real_path), "error_type": "FileNotFound", "message": "not found"})
            return

        max_size = config.indexer.max_file_size_mb
        if max_size and stat.st_size > max_size * 1024 * 1024:
            work_queue.put({"type": "unchanged", "path": str(real_path)})
            return

        ext = ".eml"
        meta = DocumentMeta(
            source=source,
            path=str(real_path),
            filename=real_path.name,
            extension=ext,
            size_bytes=stat.st_size,
            ctime=stat.st_ctime,
            mtime=stat.st_mtime,
            atime=stat.st_atime if hasattr(stat, "st_atime") else None,
            owner=get_owner(stat),
            last_editor=get_owner(stat),
        )
        try:
            conn = get_thread_conn()
            cur = conn.execute("SELECT size_bytes, mtime FROM documents WHERE path = ?", (str(real_path),))
            existing_row = cur.fetchone()
            if existing_row and existing_row[0] == meta.size_bytes and existing_row[1] == meta.mtime:
                work_queue.put({"type": "unchanged", "path": str(real_path)})
                return
            meta_existing = bool(existing_row)
        except Exception:
            meta_existing = False

        try:
            WARN_CONTEXT.path = str(real_path)
            fill_content(meta, real_path, ext)
            if stop_event.is_set():
                return
            work_queue.put({"type": "document", "meta": meta, "existing": meta_existing})
        except Exception as exc:
            logger.error("%s %s %s", type(exc).__name__, real_path, real_path.name)
            work_queue.put(
                {
                    "type": "error",
                    "path": str(real_path),
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        finally:
            WARN_CONTEXT.path = None
            touch_heartbeat()

    exclude_set = {p.lower() for p in getattr(config.indexer, "exclude_dirs", []) if p}

    def iter_files():
        for root, source in file_entries:
            if not root.exists():
                logger.error("Wurzelpfad nicht gefunden: %s", root)
                counters["errors"] += 1
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                # prune directories
                pruned = []
                for d in list(dirnames):
                    rel = Path(dirpath, d).relative_to(root)
                    rel_str = str(rel)
                    if d.lower() in exclude_set or rel_str.lower() in exclude_set:
                        pruned.append(d)
                for d in pruned:
                    dirnames.remove(d)
                for name in filenames:
                    path = Path(dirpath) / name
                    if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                        yield path, path, source

    def iter_maildir_files():
        for root, source in maildir_entries:
            if not root.exists():
                logger.error("Maildir-Wurzel nicht gefunden: %s", root)
                counters["errors"] += 1
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                # skip quarantine folders
                dirnames[:] = [d for d in dirnames if d.lower() != ".quarantine"]
                if Path(dirpath).name.lower() in {"cur", "new"}:
                    for name in filenames:
                        path = Path(dirpath) / name
                        yield path, source

    max_outstanding = max(32, config.indexer.worker_count * 8)
    futures: List[concurrent.futures.Future] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.indexer.worker_count) as pool:
        for real_path, original_path, source in iter_files():
            if stop_event.is_set():
                break
            total_files += 1
            if total_files == 1 or total_files % 200 == 0:
                update_live_status(counters, total_files=total_files)
            while len(futures) >= max_outstanding:
                done, not_done = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
                futures = list(not_done)
                for _ in done:
                    pass
            futures.append(pool.submit(process_file_task, real_path, original_path, source))
        for real_path, source in iter_maildir_files():
            if stop_event.is_set():
                break
            total_files += 1
            if total_files == 1 or total_files % 200 == 0:
                update_live_status(counters, total_files=total_files)
            while len(futures) >= max_outstanding:
                done, not_done = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
                futures = list(not_done)
                for _ in done:
                    pass
            futures.append(pool.submit(process_mail_task, real_path, source))
        update_live_status(counters, total_files=total_files)
        for fut in concurrent.futures.as_completed(futures):
            fut.result()

    work_queue.put(None)
    writer_thread.join()
    flush_live_status(force=True)

    with db.get_conn() as conn:
        post_check = readiness.check_sources_ready(file_entries + maildir_entries, existing_counts)
        if not post_check.ok:
            finish_message = finish_message or post_check.message or "Netzlaufwerk nicht bereit"
            logger.warning("Indexlauf #%s: Cleanup übersprungen: %s", run_id, finish_message)
            counters["errors"] += 1
            counters["removed"] = 0
            status_override = status_override or "error"
            db.cleanup_scanned_paths(conn, run_id)
        else:
            removed_entries = db.remove_documents_not_scanned(conn, run_id, [src for _, src in file_entries + maildir_entries])
            counters["removed"] = len(removed_entries)
            db.cleanup_scanned_paths(conn, run_id)

    end_time = datetime.now(timezone.utc).isoformat()
    status = status_override or ("stopped" if stop_event.is_set() else ("completed" if counters["errors"] == 0 else "completed_with_errors"))
    update_live_status(counters, status=status, message=finish_message, finished=True)
    logger.info(
        "Indexlauf #%s beendet mit Status %s | gescannt=%s, added=%s, updated=%s, removed=%s, errors=%s, skipped=%s",
        run_id,
        status,
        counters["scanned"],
        counters["added"],
        counters["updated"],
        counters["removed"],
        counters["errors"],
        counters["skipped"],
    )
    with db.get_conn() as conn:
        db.record_index_run_finish(
            conn,
            run_id,
            end_time,
            status,
            counters["scanned"],
            counters["added"],
            counters["updated"],
            counters["removed"],
            counters["errors"],
            finish_message,
        )
    clear_run_id()
    send_report_if_configured(config, counters, status, run_id, start_time, end_time)
    return counters


def save_run_id(run_id: int) -> None:
    RUN_STATUS_FILE.parent.mkdir(exist_ok=True)
    RUN_STATUS_FILE.write_text(str(run_id))


def load_run_id() -> Optional[int]:
    if RUN_STATUS_FILE.exists():
        try:
            return int(RUN_STATUS_FILE.read_text().strip())
        except Exception:
            return None
    return None


def clear_run_id() -> None:
    if RUN_STATUS_FILE.exists():
        RUN_STATUS_FILE.unlink()
    if HEARTBEAT_FILE.exists():
        HEARTBEAT_FILE.unlink()


def touch_heartbeat() -> None:
    try:
        HEARTBEAT_FILE.parent.mkdir(exist_ok=True)
        HEARTBEAT_FILE.write_text(str(int(time.time())))
    except Exception:
        pass


def fill_content(meta: DocumentMeta, path: Path, ext: str) -> None:
    if ext == ".pdf":
        meta.content = extractors.extract_pdf(path)
        meta.title_or_subject = meta.filename
    elif ext == ".rtf":
        meta.content = extractors.extract_rtf(path)
        meta.title_or_subject = meta.filename
    elif ext == ".txt":
        meta.content = extractors.read_text_file(path)
        meta.title_or_subject = meta.filename
    elif ext == ".msg":
        msg = extractors.extract_msg_file(path)
        meta.content = msg["content"]
        meta.title_or_subject = msg["title_or_subject"]
        meta.msg_from = msg["msg_from"]
        meta.msg_to = msg["msg_to"]
        meta.msg_cc = msg["msg_cc"]
        meta.msg_subject = msg["msg_subject"]
        meta.msg_date = msg["msg_date"]
    elif ext == ".eml":
        msg = extractors.extract_mail_file(path)
        meta.content = msg["content"]
        meta.title_or_subject = msg["title_or_subject"]
        meta.msg_from = msg["msg_from"]
        meta.msg_to = msg["msg_to"]
        meta.msg_cc = msg["msg_cc"]
        meta.msg_subject = msg["msg_subject"]
        meta.msg_date = msg["msg_date"]
        meta.msg_message_id = msg.get("msg_message_id")
        meta.msg_attachments = msg.get("msg_attachments")
    else:
        meta.content = ""
        meta.title_or_subject = meta.filename


def get_owner(stat) -> Optional[str]:
    try:
        import pwd

        return pwd.getpwuid(stat.st_uid).pw_name
    except Exception:
        return None


def send_report_if_configured(
    config: CentralConfig,
    counters: Dict[str, int],
    status: str,
    run_id: int,
    started_at: str,
    finished_at: str,
) -> None:
    try:
        reporting.send_run_report_email(config, run_id)
    except Exception as exc:
        logger.error("Report-Versand fehlgeschlagen: %s", exc)


if __name__ == "__main__":  # pragma: no cover
    from app.config_loader import load_config

    cfg = load_config()
    result = run_index_lauf(cfg)
    print("Indexlauf abgeschlossen:", result)
