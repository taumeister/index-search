import json
import os
import platform
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil

from app import metrics_db
from app.metrics_config import load_thresholds

MAX_EVENTS = 10000
CHUNK_EVENT_LIMIT = 500
RUN_DIR = Path("data/metrics_runs")
RUN_DIR.mkdir(parents=True, exist_ok=True)


def init_metrics() -> None:
    metrics_db.init_db()


def _prune_events(conn) -> None:
    cur = conn.execute("SELECT COUNT(*) FROM metrics_events")
    total = cur.fetchone()[0] or 0
    if total <= MAX_EVENTS:
        return
    to_delete = max(CHUNK_EVENT_LIMIT, total - MAX_EVENTS)
    conn.execute(
        "DELETE FROM metrics_events WHERE id IN (SELECT id FROM metrics_events ORDER BY ts ASC LIMIT ?)",
        (to_delete,),
    )


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


def _compute_throughput_mb_s(bytes_sent: Optional[int], transfer_ms: Optional[float]) -> Optional[float]:
    if bytes_sent is None or transfer_ms is None:
        return None
    if transfer_ms <= 0:
        return None
    return (bytes_sent / (1024 * 1024)) / (transfer_ms / 1000)


def record_event(event: Dict[str, Any]) -> None:
    event = dict(event)
    event.setdefault("ts", time.time())
    event.setdefault("cause", infer_cause(event))
    with metrics_db.get_conn() as conn:
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


def _build_histogram(values: List[float]) -> List[Dict[str, Any]]:
    if not values:
        return []
    max_v = max(values)
    edges = [0, 250, 500, 750, 1000, 1500, 2000, 3000, 5000]
    while edges[-1] < max_v:
        edges.append(edges[-1] + 3000)
    buckets = [0 for _ in range(len(edges))]
    for v in values:
        idx = 0
        while idx + 1 < len(edges) and v >= edges[idx + 1]:
            idx += 1
        buckets[idx] += 1
    labels = []
    for i, edge in enumerate(edges):
        if i == len(edges) - 1:
            label = f">{edge} ms"
        else:
            label = f"{edge}-{edges[i+1]} ms"
        labels.append(label)
    return [{"label": labels[i], "count": buckets[i]} for i in range(len(buckets))]


def _status_order(status: str) -> int:
    return {"red": 3, "yellow": 2, "green": 1, "unknown": 0}.get(status, 0)


def _worst_status(statuses: List[str]) -> str:
    if not statuses:
        return "unknown"
    return max(statuses, key=_status_order)


def _eval_threshold(value: Optional[float], rule: Dict[str, Any]) -> Tuple[str, str]:
    """
    Gibt (status, threshold_label) zurück.
    """
    if value is None:
        return "unknown", "kein Wert"
    if "warn_below" in rule or "crit_below" in rule:
        warn = rule.get("warn_below")
        crit = rule.get("crit_below")
        if crit is not None and value < crit:
            return "red", f"< {crit}"
        if warn is not None and value < warn:
            return "yellow", f"< {warn}"
        return "green", f">= {warn or crit or '?'}"
    warn = rule.get("warn")
    crit = rule.get("crit")
    if crit is not None and value >= crit:
        return "red", f">= {crit}"
    if warn is not None and value >= warn:
        return "yellow", f">= {warn}"
    return "green", f"< {warn or crit or '?'}"


def _format_ms(val: Optional[float]) -> str:
    if val is None:
        return "–"
    return f"{val:.0f} ms"


def _format_pct(val: Optional[float]) -> str:
    if val is None:
        return "–"
    return f"{val:.1f}%"


def _format_rate(val: Optional[float]) -> str:
    if val is None:
        return "–"
    return f"{val:.1f}/min"


def _format_mbps(val: Optional[float]) -> str:
    if val is None:
        return "–"
    return f"{val:.1f} MB/s"


def _collect_environment() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "host": platform.node(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }
    try:
        vm = psutil.virtual_memory()
        info["mem_total_mb"] = round(vm.total / (1024 * 1024), 2)
    except Exception:
        info["mem_total_mb"] = None
    mounts = []
    try:
        for part in psutil.disk_partitions(all=False):
            mounts.append(
                {
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "opts": part.opts,
                }
            )
    except Exception:
        mounts = []
    info["mounts"] = mounts
    return info


def get_summary(
    window_seconds: int = 24 * 3600,
    endpoint: Optional[str] = None,
    extension: Optional[str] = None,
    is_test: Optional[bool] = None,
    test_run_id: Optional[str] = None,
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
    if test_run_id:
        clauses.append("test_run_id = ?")
        params.append(test_run_id)
    where_sql = " AND ".join(clauses)
    query = f"""
        SELECT server_total_ms, server_ttfb_ms, smb_first_read_ms, transfer_ms, bytes_sent, cause, status_code
        FROM metrics_events WHERE {where_sql}
    """
    totals: List[float] = []
    ttfb: List[float] = []
    firsts: List[float] = []
    transfers: List[float] = []
    causes: Dict[str, int] = {}
    throughput: List[float] = []
    failures = 0
    with metrics_db.get_conn() as conn:
        for row in conn.execute(query, params):
            if row[0] is not None:
                totals.append(float(row[0]))
            if row[1] is not None:
                ttfb.append(float(row[1]))
            if row[2] is not None:
                firsts.append(float(row[2]))
            if row[3] is not None:
                transfers.append(float(row[3]))
            thr = _compute_throughput_mb_s(row[4], row[3])
            if thr is not None:
                throughput.append(thr)
            cause = row[5] or "unknown"
            causes[cause] = causes.get(cause, 0) + 1
            status_code = row[6]
            if status_code is not None and status_code >= 400:
                failures += 1
    count = len(totals)
    error_rate = failures / max(1, count) if count else 0.0
    previews_per_min = count / (window_seconds / 60.0)
    thresholds = load_thresholds()
    system_slots = get_system_slots(limit=120)
    histogram = _build_histogram(totals)
    health = build_health(
        {
            "totals": _quantiles(totals),
            "ttfb": _quantiles(ttfb),
            "smb_first_read": _quantiles(firsts),
            "transfer": _quantiles(transfers),
            "throughput_mb_s": _quantiles(throughput),
            "error_rate": error_rate,
            "previews_per_min": previews_per_min,
            "count": count,
        },
        system_slots,
        thresholds,
    )
    return {
        "count": count,
        "totals": _quantiles(totals),
        "ttfb": _quantiles(ttfb),
        "smb_first_read": _quantiles(firsts),
        "transfer": _quantiles(transfers),
        "throughput_mb_s": _quantiles(throughput),
        "causes": causes,
        "since": since,
        "error_rate": error_rate,
        "previews_per_min": previews_per_min,
        "histogram": histogram,
        "health": health,
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
    with metrics_db.get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    events: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["throughput_mb_s"] = _compute_throughput_mb_s(item.get("bytes_sent"), item.get("transfer_ms"))
        events.append(item)
    return events


def record_system_slot(slot_ts: Optional[int] = None) -> None:
    slot_ts = slot_ts or int(time.time() // 60 * 60)
    cpu = psutil.cpu_percent(interval=None)
    vm = psutil.virtual_memory()
    mem = vm.percent
    mem_total_mb = vm.total / (1024 * 1024)
    mem_available_mb = vm.available / (1024 * 1024)
    swap = None
    try:
        swap = psutil.swap_memory()
    except Exception:
        swap = None
    io_wait = 0.0
    steal = 0.0
    try:
        cpu_times = psutil.cpu_times_percent(interval=None)
        io_wait = getattr(cpu_times, "iowait", 0.0) or 0.0
        steal = getattr(cpu_times, "steal", 0.0) or 0.0
    except Exception:
        pass
    net = psutil.net_io_counters()
    disk = None
    try:
        disk = psutil.disk_io_counters()
    except Exception:
        disk = None
    faults = None
    try:
        stats = psutil.cpu_stats()
        faults = getattr(stats, "faults", None)
    except Exception:
        faults = None
    load1 = None
    try:
        load1 = os.getloadavg()[0]
    except Exception:
        load1 = None
    with metrics_db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO metrics_system_slots (
                slot_ts, cpu_percent, mem_percent, io_wait_percent,
                net_bytes_sent, net_bytes_recv,
                mem_total_mb, mem_available_mb,
                swap_total_mb, swap_used_mb,
                load1, cpu_steal_percent,
                disk_read_bytes, disk_write_bytes,
                page_faults
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slot_ts) DO UPDATE SET
                cpu_percent=excluded.cpu_percent,
                mem_percent=excluded.mem_percent,
                io_wait_percent=excluded.io_wait_percent,
                net_bytes_sent=excluded.net_bytes_sent,
                net_bytes_recv=excluded.net_bytes_recv,
                mem_total_mb=excluded.mem_total_mb,
                mem_available_mb=excluded.mem_available_mb,
                swap_total_mb=excluded.swap_total_mb,
                swap_used_mb=excluded.swap_used_mb,
                load1=excluded.load1,
                cpu_steal_percent=excluded.cpu_steal_percent,
                disk_read_bytes=excluded.disk_read_bytes,
                disk_write_bytes=excluded.disk_write_bytes,
                page_faults=excluded.page_faults
            """,
            (
                slot_ts,
                cpu,
                mem,
                io_wait,
                getattr(net, "bytes_sent", 0),
                getattr(net, "bytes_recv", 0),
                mem_total_mb,
                mem_available_mb,
                getattr(swap, "total", 0) / (1024 * 1024) if swap else None,
                getattr(swap, "used", 0) / (1024 * 1024) if swap else None,
                load1,
                steal,
                getattr(disk, "read_bytes", None),
                getattr(disk, "write_bytes", None),
                faults,
            ),
        )


def get_system_slots(limit: int = 1440) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 1440))
    with metrics_db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM metrics_system_slots ORDER BY slot_ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_system_slots_between(start_ts: float, end_ts: float) -> List[Dict[str, Any]]:
    with metrics_db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM metrics_system_slots WHERE slot_ts BETWEEN ? AND ? ORDER BY slot_ts ASC",
            (int(start_ts), int(end_ts)),
        ).fetchall()
    return [dict(row) for row in rows]


def _avg(values: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _delta_rate(slots: List[Dict[str, Any]], key: str) -> Optional[float]:
    if len(slots) < 2:
        return None
    newest = slots[0]
    oldest = slots[-1]
    dt = max(1, (newest.get("slot_ts") or 0) - (oldest.get("slot_ts") or 0))
    delta = (newest.get(key) or 0) - (oldest.get(key) or 0)
    if delta <= 0:
        return None
    return delta / dt


def build_health(summary: Dict[str, Any], system_slots: List[Dict[str, Any]], thresholds: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    categories: List[Dict[str, Any]] = []
    preview_p95 = (summary.get("totals") or {}).get("p95")
    preview_p50 = (summary.get("totals") or {}).get("p50")
    preview_status, preview_thresh = _eval_threshold(preview_p95, thresholds.get("preview_p95_ms", {}))
    categories.append(
        {
            "key": "preview",
            "label": "Preview-Pipeline",
            "status": preview_status,
            "value": f"p50 { _format_ms(preview_p50) }, p95 { _format_ms(preview_p95) }",
            "threshold": f"Warn ab {thresholds.get('preview_p50_ms', {}).get('warn', '–')} / Krit ab {thresholds.get('preview_p95_ms', {}).get('crit', '–')} ms",
            "detail": "Zeit bis Preview sichtbar (Events im Fenster)",
        }
    )

    throughput_status, throughput_thresh = _eval_threshold(summary.get("previews_per_min"), thresholds.get("previews_per_min", {}))
    categories.append(
        {
            "key": "throughput",
            "label": "Durchsatz",
            "status": throughput_status,
            "value": _format_rate(summary.get("previews_per_min")),
            "threshold": f"Warn < {thresholds.get('previews_per_min', {}).get('warn_below', '–')} / Krit < {thresholds.get('previews_per_min', {}).get('crit_below', '–')} pro Min",
            "detail": f"Events pro Minute im Fenster ({summary.get('count', 0)} Events)",
        }
    )

    error_status, error_thresh = _eval_threshold(summary.get("error_rate"), thresholds.get("error_rate", {}))
    categories.append(
        {
            "key": "errors",
            "label": "Fehlerquote",
            "status": error_status,
            "value": f"{(summary.get('error_rate') or 0)*100:.1f}%",
            "threshold": f"Warn ab {(thresholds.get('error_rate', {}).get('warn', 0))*100:.1f}% / Krit ab {(thresholds.get('error_rate', {}).get('crit', 0))*100:.1f}%",
            "detail": "HTTP >=400 im Fenster",
        }
    )

    smb_latency = (summary.get("smb_first_read") or {}).get("p95")
    smb_p50 = (summary.get("smb_first_read") or {}).get("p50")
    smb_status, smb_thresh = _eval_threshold(smb_latency, thresholds.get("smb_latency_p95_ms", {}))
    smb_thr = (summary.get("throughput_mb_s") or {}).get("p50")
    smb_thr_status, smb_thr_thresh = _eval_threshold(smb_thr, thresholds.get("smb_throughput_mb_s", {}))
    smb_status_final = _worst_status([smb_status, smb_thr_status])
    categories.append(
        {
            "key": "smb",
            "label": "SMB/Netz",
            "status": smb_status_final,
            "value": f"Latenz p95 { _format_ms(smb_latency) }, p50 { _format_ms(smb_p50) }; Durchsatz { _format_mbps(smb_thr) }",
            "threshold": f"Latenz warn/rot ab {thresholds.get('smb_latency_p95_ms', {}).get('warn', '–')}/{thresholds.get('smb_latency_p95_ms', {}).get('crit', '–')} ms; Durchsatz warn/rot < {thresholds.get('smb_throughput_mb_s', {}).get('warn_below', '–')}/{thresholds.get('smb_throughput_mb_s', {}).get('crit_below', '–')} MB/s",
            "detail": "Latenz erstes Read + Daten-Durchsatz im Fenster",
        }
    )

    cpu_status = "unknown"
    cpu_thresh = "–"
    io_status = "unknown"
    io_thresh = "–"
    mem_status = "unknown"
    mem_thresh = "–"
    if system_slots:
        last_slots = system_slots[: min(30, len(system_slots))]
        cpu_avg = _avg([s.get("cpu_percent") for s in last_slots])
        load_avg = _avg([s.get("load1") for s in last_slots])
        cores = os.cpu_count() or 1
        load_per_core = load_avg / cores if load_avg is not None else None
        cpu_status, cpu_thresh = _eval_threshold(cpu_avg, thresholds.get("cpu_percent", {}))
        load_status, load_thresh = _eval_threshold(load_per_core, thresholds.get("cpu_load_per_core", {}))
        cpu_status = _worst_status([cpu_status, load_status])
        cpu_thresh = f"{cpu_thresh} / {load_thresh}"

        mem_last = system_slots[0]
        mem_status, mem_thresh = _eval_threshold(mem_last.get("mem_percent"), thresholds.get("mem_used_percent", {}))
        swap_percent = None
        if mem_last.get("swap_total_mb"):
            swap_percent = (mem_last.get("swap_used_mb") or 0) / (mem_last.get("swap_total_mb") or 1) * 100
        swap_status, swap_thresh = _eval_threshold(swap_percent, thresholds.get("swap_used_percent", {}))
        mem_status = _worst_status([mem_status, swap_status])
        mem_thresh = f"{mem_thresh} / {swap_thresh}"

        io_avg = _avg([s.get("io_wait_percent") for s in last_slots])
        io_status, io_thresh = _eval_threshold(io_avg, thresholds.get("io_wait_percent", {}))
        disk_r_rate = _delta_rate(last_slots, "disk_read_bytes")
        disk_w_rate = _delta_rate(last_slots, "disk_write_bytes")
        disk_r_mb = (disk_r_rate / (1024 * 1024)) if disk_r_rate is not None else None
        disk_w_mb = (disk_w_rate / (1024 * 1024)) if disk_w_rate is not None else None
        disk_r_status, disk_r_thresh = _eval_threshold(disk_r_mb, thresholds.get("disk_read_mb_s", {}))
        disk_w_status, disk_w_thresh = _eval_threshold(disk_w_mb, thresholds.get("disk_write_mb_s", {}))
        io_status = _worst_status([io_status, disk_r_status, disk_w_status])
        io_thresh = f"{io_thresh} / {disk_r_thresh} / {disk_w_thresh}"

        net_rate = _delta_rate(last_slots, "net_bytes_recv")
        net_mbps = (net_rate / (1024 * 1024)) if net_rate is not None else None
    else:
        net_mbps = None

    categories.append(
        {
            "key": "cpu",
            "label": "CPU/Load",
            "status": cpu_status,
            "value": f"CPU {_format_pct(_avg([s.get('cpu_percent') for s in system_slots[:5]]))}, Load/core {(_avg([s.get('load1') for s in system_slots[:5]]) or 0)/(os.cpu_count() or 1):.2f}",
            "threshold": f"Warn ab {thresholds.get('cpu_percent', {}).get('warn', '–')}% / {thresholds.get('cpu_load_per_core', {}).get('warn', '–')} load/core",
            "detail": "Durchschnitt der letzten System-Slots im Fenster",
        }
    )
    categories.append(
        {
            "key": "memory",
            "label": "RAM/Swap",
            "status": mem_status,
            "value": f"RAM {_format_pct(system_slots[0].get('mem_percent') if system_slots else None)}, Swap {_format_pct(((system_slots[0].get('swap_used_mb') or 0) / (system_slots[0].get('swap_total_mb') or 1) * 100) if system_slots and system_slots[0].get('swap_total_mb') else None)}",
            "threshold": f"Warn ab {thresholds.get('mem_used_percent', {}).get('warn', '–')}% RAM / {thresholds.get('swap_used_percent', {}).get('warn', '–')}% Swap",
            "detail": "Letzter System-Slot im Fenster",
        }
    )
    categories.append(
        {
            "key": "io",
            "label": "IO/Storage",
            "status": io_status,
            "value": f"iowait {_format_pct(_avg([s.get('io_wait_percent') for s in system_slots[:5]]))}",
            "threshold": f"Warn ab {thresholds.get('io_wait_percent', {}).get('warn', '–')}% iowait; Disk warn/rot < {thresholds.get('disk_read_mb_s', {}).get('warn_below', '–')}/{thresholds.get('disk_read_mb_s', {}).get('crit_below', '–')} MB/s",
            "detail": "Durchschnitt/System-Slots im Fenster",
        }
    )
    categories.append(
        {
            "key": "network",
            "label": "Netz",
            "status": _eval_threshold(net_mbps, thresholds.get("net_throughput_mb_s", {}))[0],
            "value": f"Durchsatz {_format_mbps(net_mbps)}",
            "threshold": f"Warn/rot < {thresholds.get('net_throughput_mb_s', {}).get('warn_below', '–')}/{thresholds.get('net_throughput_mb_s', {}).get('crit_below', '–')} MB/s",
            "detail": "Empfangsrate (System-Slots im Fenster)",
        }
    )

    headline = "Keine Auffälligkeiten."
    worst = max(categories, key=lambda c: _status_order(c["status"])) if categories else None
    if summary.get("count", 0) == 0:
        headline = "Keine Daten im Zeitfenster – Testlauf/Events nötig."
    elif worst and worst["status"] == "yellow":
        headline = f"Auffällig: {worst['label']} – {worst['detail']}"
    elif worst and worst["status"] == "red":
        headline = f"Problem: {worst['label']} – {worst['detail']}"

    return {
        "categories": categories,
        "headline": headline,
        "thresholds": thresholds,
        "basis": {
            "events": summary.get("count", 0),
            "window_minutes": None,
            "note": "Alle Werte basieren auf Events/System-Slots im gewählten Zeitfenster.",
        },
    }


def reset_metrics_storage() -> None:
    metrics_db.reset_db()


def get_last_test_run_id() -> Optional[str]:
    with metrics_db.get_conn() as conn:
        row = conn.execute(
            "SELECT test_run_id FROM metrics_events WHERE is_test = 1 AND test_run_id IS NOT NULL ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None


def get_test_run_events(test_run_id: str, limit: int = 200) -> Dict[str, Any]:
    limit = max(1, min(limit, 1000))
    with metrics_db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM metrics_events WHERE test_run_id = ? ORDER BY ts DESC LIMIT ?",
            (test_run_id, limit),
        ).fetchall()
        count = conn.execute(
            "SELECT COUNT(*) FROM metrics_events WHERE test_run_id = ?", (test_run_id,)
        ).fetchone()[0]
        stats_rows = conn.execute(
            "SELECT server_total_ms, server_ttfb_ms, smb_first_read_ms, transfer_ms, cause, doc_id, path, size_bytes, extension, status_code, bytes_sent FROM metrics_events WHERE test_run_id = ?",
            (test_run_id,),
        ).fetchall()
    events = [dict(r) for r in rows]
    summary = _build_summary_from_rows(stats_rows)
    top_slow = _build_top_slow(stats_rows, limit=10)
    return {"test_run_id": test_run_id, "count": count, "events": events, "summary": summary, "top_slow": top_slow}


def _build_summary_from_rows(rows) -> Dict[str, Any]:
    totals: List[float] = []
    ttfb: List[float] = []
    firsts: List[float] = []
    transfers: List[float] = []
    causes: Dict[str, int] = {}
    throughput: List[float] = []
    failures = 0
    for r in rows:
        total = r["server_total_ms"]
        if total is not None:
            totals.append(float(total))
        if r["server_ttfb_ms"] is not None:
            ttfb.append(float(r["server_ttfb_ms"]))
        if r["smb_first_read_ms"] is not None:
            firsts.append(float(r["smb_first_read_ms"]))
        if r["transfer_ms"] is not None:
            transfers.append(float(r["transfer_ms"]))
        cause = r["cause"] or "unknown"
        causes[cause] = causes.get(cause, 0) + 1
        thr = _compute_throughput_mb_s(r["bytes_sent"] if "bytes_sent" in r.keys() else None, r["transfer_ms"])
        if thr is not None:
            throughput.append(thr)
        status_code = r["status_code"] if "status_code" in r.keys() else None
        if status_code is not None and status_code >= 400:
            failures += 1
    total_count = max(1, len(rows))
    error_rate = failures / total_count
    return {
        "totals": _quantiles(totals),
        "ttfb": _quantiles(ttfb),
        "smb_first_read": _quantiles(firsts),
        "transfer": _quantiles(transfers),
        "causes": causes,
        "throughput_mb_s": _quantiles(throughput),
        "error_rate": error_rate,
    }


def _build_top_slow(rows, limit: int = 10) -> List[Dict[str, Any]]:
    data = []
    for r in rows:
        total = r["server_total_ms"]
        if total is None:
            continue
        data.append(
            {
                "doc_id": r["doc_id"],
                "path": r["path"],
                "size_bytes": r["size_bytes"],
                "extension": r["extension"],
                "total_ms": float(total),
                "ttfb_ms": r["server_ttfb_ms"],
                "smb_ms": r["smb_first_read_ms"],
                "transfer_ms": r["transfer_ms"],
                "cause": r["cause"],
                "status_code": r["status_code"],
                "bytes_sent": r["bytes_sent"] if "bytes_sent" in r.keys() else None,
            }
        )
    data.sort(key=lambda x: x.get("total_ms") or 0, reverse=True)
    return data[:limit]


def _status_score(status: str) -> int:
    return {"red": 3, "yellow": 2, "green": 1}.get(status, 0)


def _build_diagnosis(summary: Dict[str, Any], system_slots: List[Dict[str, Any]], thresholds: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    causes: List[Dict[str, Any]] = []
    preview_p95 = (summary.get("totals") or {}).get("p95")
    throughput = summary.get("previews_per_min")
    error_rate = summary.get("error_rate")
    smb_p95 = (summary.get("smb_first_read") or {}).get("p95")
    smb_thr = (summary.get("throughput_mb_s") or {}).get("p50")

    cpu_avg = _avg([s.get("cpu_percent") for s in system_slots]) if system_slots else None
    load_avg = _avg([s.get("load1") for s in system_slots]) if system_slots else None
    cores = os.cpu_count() or 1
    load_per_core = (load_avg / cores) if load_avg is not None else None
    mem_last = system_slots[-1] if system_slots else {}
    mem_pct = mem_last.get("mem_percent")
    swap_pct = None
    if mem_last.get("swap_total_mb"):
        swap_pct = (mem_last.get("swap_used_mb") or 0) / (mem_last.get("swap_total_mb") or 1) * 100
    io_wait = _avg([s.get("io_wait_percent") for s in system_slots]) if system_slots else None
    net_mbps = None
    if system_slots and len(system_slots) >= 2:
        rate = _delta_rate(system_slots, "net_bytes_recv")
        net_mbps = (rate / (1024 * 1024)) if rate is not None else None

    def add_cause(key: str, label: str, status: str, evidence: List[str]) -> None:
        causes.append({"key": key, "label": label, "status": status, "evidence": evidence})

    smb_status, _ = _eval_threshold(smb_p95, thresholds.get("smb_latency_p95_ms", {}))
    smb_thr_status, _ = _eval_threshold(smb_thr, thresholds.get("smb_throughput_mb_s", {}))
    if _status_score(smb_status) >= 2 or _status_score(smb_thr_status) >= 2:
        add_cause(
            "smb",
            "SMB/Netz",
            _worst_status([smb_status, smb_thr_status]),
            [
                f"SMB Latenz p95 { _format_ms(smb_p95) }",
                f"Durchsatz { _format_mbps(smb_thr) }",
            ],
        )

    cpu_status, _ = _eval_threshold(cpu_avg, thresholds.get("cpu_percent", {}))
    load_status, _ = _eval_threshold(load_per_core, thresholds.get("cpu_load_per_core", {}))
    cpu_worst = _worst_status([cpu_status, load_status])
    if _status_score(cpu_worst) >= 2:
        add_cause(
            "cpu",
            "CPU/Load",
            cpu_worst,
            [f"CPU { _format_pct(cpu_avg) }", f"Load/core {load_per_core:.2f}" if load_per_core is not None else "Load/core –"],
        )

    mem_status, _ = _eval_threshold(mem_pct, thresholds.get("mem_used_percent", {}))
    swap_status, _ = _eval_threshold(swap_pct, thresholds.get("swap_used_percent", {}))
    mem_worst = _worst_status([mem_status, swap_status])
    if _status_score(mem_worst) >= 2:
        add_cause(
            "memory",
            "RAM/Swap",
            mem_worst,
            [f"RAM { _format_pct(mem_pct) }", f"Swap { _format_pct(swap_pct) }"],
        )

    io_status, _ = _eval_threshold(io_wait, thresholds.get("io_wait_percent", {}))
    if _status_score(io_status) >= 2:
        add_cause("io", "I/O/Storage", io_status, [f"iowait { _format_pct(io_wait) }"])

    net_status, _ = _eval_threshold(net_mbps, thresholds.get("net_throughput_mb_s", {}))
    if _status_score(net_status) >= 2:
        add_cause("net", "Netz", net_status, [f"Durchsatz { _format_mbps(net_mbps) }"])

    preview_status, _ = _eval_threshold(preview_p95, thresholds.get("preview_p95_ms", {}))
    if _status_score(preview_status) >= 2 and all(_status_score(c.get("status")) < 2 for c in causes):
        add_cause("pipeline", "Preview-Pipeline", preview_status, [f"Preview p95 { _format_ms(preview_p95) }"])

    th_status, _ = _eval_threshold(throughput, thresholds.get("previews_per_min", {}))
    if _status_score(th_status) >= 2:
        add_cause("throughput", "Durchsatz niedrig", th_status, [f"{_format_rate(throughput)}"])

    err_status, _ = _eval_threshold(error_rate, thresholds.get("error_rate", {}))
    if _status_score(err_status) >= 2:
        add_cause("errors", "Fehlerquote", err_status, [f"{(error_rate or 0)*100:.1f}% Fehler"])

    if not causes:
        ok_evidence = [
            f"Preview p95 { _format_ms(preview_p95) }",
            f"SMB p95 { _format_ms(smb_p95) }",
            f"Durchsatz { _format_mbps(smb_thr) }",
            f"CPU { _format_pct(cpu_avg) }",
            f"RAM { _format_pct(mem_pct) }",
        ]
        causes.append({"key": "ok", "label": "Keine Auffälligkeiten", "status": "green", "evidence": ok_evidence})

    causes.sort(key=lambda c: _status_score(c["status"]), reverse=True)
    top = causes[:3]
    overall = _worst_status([c["status"] for c in top])
    headline = "Keine Auffälligkeiten."
    if overall == "yellow":
        headline = f"Auffällig: {top[0]['label']} – {', '.join(top[0].get('evidence', []) or [])}"
    elif overall == "red":
        headline = f"Problem: {top[0]['label']} – {', '.join(top[0].get('evidence', []) or [])}"
    return {"overall": overall, "headline": headline, "causes": top}


def build_run_artifact(test_run_id: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    events_data = get_test_run_events(test_run_id, limit=1000)
    events = events_data.get("events", [])
    summary = events_data.get("summary", {})
    thresholds = load_thresholds()
    ts_values = [ev.get("ts") for ev in events if ev.get("ts")]
    if ts_values:
        start_ts = min(ts_values)
        end_ts = max(ts_values)
        slots = get_system_slots_between(start_ts - 60, end_ts + 60)
    else:
        start_ts = time.time()
        end_ts = start_ts
        slots = []
    duration_sec = max(1, end_ts - start_ts)
    previews_per_min = (events_data.get("count", 0) / (duration_sec / 60.0)) if duration_sec else None
    summary["previews_per_min"] = previews_per_min
    summary["duration_sec"] = duration_sec
    diagnosis = _build_diagnosis(
        {
            "totals": summary.get("totals", {}),
            "smb_first_read": summary.get("smb_first_read", {}),
            "throughput_mb_s": summary.get("throughput_mb_s", {}),
            "previews_per_min": summary.get("previews_per_min"),
            "error_rate": summary.get("error_rate"),
            "count": events_data.get("count", 0),
        },
        slots,
        thresholds,
    )
    artifact = {
        "run_id": test_run_id,
        "created": events[0].get("ts") if events else time.time(),
        "params": params or {},
        "environment": _collect_environment(),
        "summary": summary,
        "top_slow": events_data.get("top_slow", []),
        "count": events_data.get("count", 0),
        "events": events[:200],
        "timeline": [
            {
                "idx": idx + 1,
                "doc_id": ev.get("doc_id"),
                "total_ms": ev.get("server_total_ms"),
                "smb_ms": ev.get("smb_first_read_ms"),
                "transfer_ms": ev.get("transfer_ms"),
                "ts": ev.get("ts"),
            }
            for idx, ev in enumerate(events[:200])
        ],
        "system_slots": slots,
        "diagnosis": diagnosis,
    }
    return artifact


def save_test_run_artifact(test_run_id: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    artifact = build_run_artifact(test_run_id, params=params)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    path = RUN_DIR / f"{test_run_id}.json"
    try:
        path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    except Exception:
        pass
    return artifact


def list_run_artifacts(limit: int = 20) -> List[Dict[str, Any]]:
    if not RUN_DIR.exists():
        return []
    files = sorted(RUN_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    items = []
    for path in files[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append(
                {
                    "run_id": data.get("run_id") or path.stem,
                    "created": data.get("created"),
                    "params": data.get("params", {}),
                    "headline": (data.get("diagnosis") or {}).get("headline") or (data.get("summary") or {}).get("health", {}).get("headline"),
                }
            )
        except Exception:
            continue
    return items


def load_run_artifact(run_id: str) -> Optional[Dict[str, Any]]:
    path = RUN_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "diagnosis" not in data or "summary" not in data:
            rebuilt = build_run_artifact(run_id, params=data.get("params"))
            return rebuilt
        return data
    except Exception:
        try:
            return build_run_artifact(run_id, params=None)
        except Exception:
            return None
