import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CONFIG_DB_PATH = Path("config/config.db")


def ensure_db() -> None:
    CONFIG_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(CONFIG_DB_PATH) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS roots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                label TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            """
        )
        seed_defaults(conn)
        conn.commit()


def seed_defaults(conn: sqlite3.Connection) -> None:
    defaults: Dict[str, str] = {
        "base_data_root": "/data",
        "worker_count": "2",
        "max_file_size_mb": "",
        "default_preview": "panel",
        "snippet_length": "160",
        "logging_level": "INFO",
        "log_dir": "logs",
        "rotation_mb": "10",
        "send_report_enabled": "0",
    }
    for key, value in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
            (key, value),
        )


@contextmanager
def get_conn():
    ensure_db()
    conn = sqlite3.connect(CONFIG_DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with get_conn() as conn:
        cur = conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def list_roots(active_only: bool = True) -> List[Tuple[str, str, int, bool]]:
    with get_conn() as conn:
        sql = "SELECT path, label, id, active FROM roots"
        params: List = []
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY id ASC"
        rows = conn.execute(sql, params).fetchall()
        return [(row[0], row[1], row[2], bool(row[3]) if len(row) > 3 else True) for row in rows]


def add_root(path: str, label: Optional[str] = None, active: bool = True) -> int:
    label = label or Path(path).name
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO roots(path, label, active) VALUES (?, ?, ?)",
            (path, label, 1 if active else 0),
        )
        return cur.lastrowid


def delete_root(root_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM roots WHERE id = ?", (root_id,))


def update_root_active(root_id: int, active: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE roots SET active = ?, updated_at = datetime('now') WHERE id = ?",
            (1 if active else 0, root_id),
        )
