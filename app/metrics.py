import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil

from app.db.datenbank import DB_PATH


MAX_EVENTS = 10000
CHUNK_EVENT_LIMIT = 500


@contextmanager
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_metrics() -> None:
    with _conn() as conn:
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
                net_bytes_recv INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_metrics_events_ts ON metrics_events(ts);
            CREATE INDEX IF NOT EXISTS idx_metrics_events_endpoint ON metrics_events(endpoint);
            CREATE INDEX IF NOT EXISTS idx_metrics_events_doc ON metrics_events(doc_id);
            """
        )


def _prune_events(conn: sqlite3.Connection) -> None:
    cur = conn.execute("SELECT COUNT(*) FROM metrics_events")
    total = cur.fetchone()[0] or 0
    if total <= MAX_EVENTS:
        return
    to_delete = max(CHUNK_EVENT_LIMIT, total - MAX_EVENTS)
    conn.execute(
        "DELETE FROM metrics_events WHERE id IN (SELECT id FROM metrics_events ORDER BY ts ASC LIMIT ?)",
        (to_delete,),
    )


def _size_class(size_bytes: Optional[int]) -> str:
    if size_bytes is None:
        return "unknown"
    if size_bytes < 256 * 1024:
        return "<256K"
    if size_bytes < 1 * 1024 * 1024:
        return "256K-1M"
    if size_bytes < 5 * 1024 * 1024:
        return "1-5M"
    if size_bytes < 20 * 1024 * 1024:
        return "5-20M"
    return ">20M"


def infer_cause(event: Dict[str, Any]) -> str:
    first = event.get("smb_first_read_ms") or 0.0
    transfer_ms = event.get("transfer_ms") or 0.0
    total = event.get("server_total_ms") or 0.0
    bytes_sent = event.get("bytes_sent") or 0
    client_render = 0.0
    if event.get("client_render_end_ts") and event.get("client_click_ts"):
        client_render = (event["client_render_end_ts"] - event["client_click_ts"]) * 1000

    if first > 300:
        return "smb_latency"
    if transfer_ms > 0 and bytes_sent > 0:
        throughput = bytes_sent / (transfer_ms / 1000)
        if throughput < 2 * 1024 * 1024:
            return "net_throughput"
    if client_render and client_render > max(total, transfer_ms, first) * 1.5:
        return "client_render"
    if total > 2000:
        return "server_cpu"
    return "ok"


def record_event(event: Dict[str, Any]) -> None:
    event = dict(event)
    event.setdefault("ts", time.time())
    event.setdefault("cause", infer_cause(event))
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO metrics_events (
                ts, endpoint, doc_id, path, source, size_bytes, extension, is_test, test_run_id,
                server_ttfb_ms, server_total_ms, smb_first_read_ms, transfer_ms, bytes_sent, status_code,
                client_click_ts, client_resp_start_ts, client_resp_end_ts, client_render_end_ts,
                user_agent, slot_ts, cause
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event.get("ts"),
                event.get("endpoint"),
                event.get("doc_id"),
                event.get("path"),
                event.get("source"),
                event.get("size_bytes"),
                event.get("extension"),
                1 if event.get("is_test") else 0,
                event.get("test_run_id"),
                event.get("server_ttfb_ms"),
                event.get("server_total_ms"),
                event.get("smb_first_read_ms"),
                event.get("transfer_ms"),
                event.get("bytes_sent"),
                event.get("status_code"),
                event.get("client_click_ts"),
                event.get("client_resp_start_ts"),
                event.get("client_resp_end_ts"),
                event.get("client_render_end_ts"),
                event.get("user_agent"),
                event.get("slot_ts"),
                event.get("cause"),
            ),
        )
        _prune_events(conn)


def _quantiles(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"p50": None, "p95": None, "p99": None}
    values_sorted = sorted(values)
    n = len(values_sorted)

    def pick(p: float) -> float:
        idx = int(max(0, min(n - 1, round(p * (n - 1)))))
        return values_sorted[idx]

    return {"p50": pick(0.5), "p95": pick(0.95), "p99": pick(0.99)}


def get_summary(
    window_seconds: int = 24 * 3600,
    endpoint: Optional[str] = None,
    extension: Optional[str] = None,
    is_test: Optional[bool] = None,
) -> Dict[str, Any]:
    now_ts = time.time()
    since = now_ts - window_seconds
    clauses = ["ts >= ?"]
    params: List[Any] = [since]
    if endpoint:
        clauses.append("endpoint = ?")
        params.append(endpoint)
    if extension:
        clauses.append("extension = ?")
        params.append(extension)
    if is_test is not None:
        clauses.append("is_test = ?")
        params.append(1 if is_test else 0)
    where_sql = " AND ".join(clauses)
    query = f"SELECT server_total_ms, server_ttfb_ms, smb_first_read_ms, transfer_ms, bytes_sent, cause FROM metrics_events WHERE {where_sql}"
    totals: List[float] = []
    ttfb: List[float] = []
    firsts: List[float] = []
    transfers: List[float] = []
    causes: Dict[str, int] = {}
    with _conn() as conn:
        for row in conn.execute(query, params):
            if row[0] is not None:
                totals.append(float(row[0]))
            if row[1] is not None:
                ttfb.append(float(row[1]))
            if row[2] is not None:
                firsts.append(float(row[2]))
            if row[3] is not None:
                transfers.append(float(row[3]))
            cause = row[5] or "unknown"
            causes[cause] = causes.get(cause, 0) + 1
    return {
        "count": len(totals),
        "totals": _quantiles(totals),
        "ttfb": _quantiles(ttfb),
        "smb_first_read": _quantiles(firsts),
        "transfer": _quantiles(transfers),
        "causes": causes,
        "since": since,
    }


def get_recent_events(limit: int = 100, is_test: Optional[bool] = None) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 1000))
    clauses = []
    params: List[Any] = []
    if is_test is not None:
        clauses.append("is_test = ?")
        params.append(1 if is_test else 0)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM metrics_events {where_sql} ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    with _conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


_slot_lock = threading.Lock()


def record_system_slot(slot_ts: Optional[int] = None) -> None:
    slot_ts = slot_ts or int(time.time() // 60 * 60)
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory().percent
    io_wait = 0.0
    try:
        cpu_times = psutil.cpu_times_percent(interval=None)
        io_wait = getattr(cpu_times, "iowait", 0.0) or 0.0
    except Exception:
        pass
    net = psutil.net_io_counters()
    with _conn() as conn, _slot_lock:
        conn.execute(
            """
            INSERT INTO metrics_system_slots (slot_ts, cpu_percent, mem_percent, io_wait_percent, net_bytes_sent, net_bytes_recv)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(slot_ts) DO UPDATE SET
                cpu_percent=excluded.cpu_percent,
                mem_percent=excluded.mem_percent,
                io_wait_percent=excluded.io_wait_percent,
                net_bytes_sent=excluded.net_bytes_sent,
                net_bytes_recv=excluded.net_bytes_recv
            """,
            (
                slot_ts,
                cpu,
                mem,
                io_wait,
                getattr(net, "bytes_sent", 0),
                getattr(net, "bytes_recv", 0),
            ),
        )


def get_system_slots(limit: int = 1440) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 1440))
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM metrics_system_slots ORDER BY slot_ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
