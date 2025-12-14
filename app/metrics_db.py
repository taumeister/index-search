import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

METRICS_DB_PATH = Path("data/metrics.db")
_lock = threading.Lock()


@contextmanager
def get_conn():
    METRICS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        conn = sqlite3.connect(METRICS_DB_PATH)
        conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn, table: str, column: str, col_type: str) -> None:
    cur = conn.execute(f"PRAGMA table_info({table})")
    names = {row[1] for row in cur.fetchall()}
    if column not in names:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metrics_events (
                id INTEGER PRIMARY KEY,
                ts REAL NOT NULL,
                endpoint TEXT NOT NULL,
                doc_id INTEGER,
                path TEXT,
                source TEXT,
                size_bytes INTEGER,
                extension TEXT,
                is_test INTEGER DEFAULT 0,
                test_run_id TEXT,
                server_ttfb_ms REAL,
                server_total_ms REAL,
                smb_first_read_ms REAL,
                transfer_ms REAL,
                bytes_sent INTEGER,
                status_code INTEGER,
                client_click_ts REAL,
                client_resp_start_ts REAL,
                client_resp_end_ts REAL,
                client_render_end_ts REAL,
                user_agent TEXT,
                slot_ts INTEGER,
                cause TEXT
            );

            CREATE TABLE IF NOT EXISTS metrics_system_slots (
                slot_ts INTEGER PRIMARY KEY,
                cpu_percent REAL,
                mem_percent REAL,
                io_wait_percent REAL,
                net_bytes_sent INTEGER,
                net_bytes_recv INTEGER,
                mem_total_mb REAL,
                mem_available_mb REAL,
                swap_total_mb REAL,
                swap_used_mb REAL,
                load1 REAL,
                cpu_steal_percent REAL,
                disk_read_bytes INTEGER,
                disk_write_bytes INTEGER,
                page_faults INTEGER
            );
            """
        )
        _ensure_column(conn, "metrics_system_slots", "mem_total_mb", "REAL")
        _ensure_column(conn, "metrics_system_slots", "mem_available_mb", "REAL")
        _ensure_column(conn, "metrics_system_slots", "swap_total_mb", "REAL")
        _ensure_column(conn, "metrics_system_slots", "swap_used_mb", "REAL")
        _ensure_column(conn, "metrics_system_slots", "load1", "REAL")
        _ensure_column(conn, "metrics_system_slots", "cpu_steal_percent", "REAL")
        _ensure_column(conn, "metrics_system_slots", "disk_read_bytes", "INTEGER")
        _ensure_column(conn, "metrics_system_slots", "disk_write_bytes", "INTEGER")
        _ensure_column(conn, "metrics_system_slots", "page_faults", "INTEGER")


def reset_db() -> None:
    if METRICS_DB_PATH.exists():
        METRICS_DB_PATH.unlink()
    init_db()
