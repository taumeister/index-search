import concurrent.futures
import json
import logging
import os
import smtplib
import time
from dataclasses import dataclass, asdict
from email.message import EmailMessage
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import queue
import threading

from app.config_loader import CentralConfig
from app.db import datenbank as db
from app.db.datenbank import DocumentMeta
from app.indexer import extractors

logger = logging.getLogger("indexer")

stop_event = threading.Event()


SUPPORTED_EXTENSIONS = {".pdf", ".rtf", ".msg", ".txt"}
RUN_STATUS_FILE = Path("data/index.run")
HEARTBEAT_FILE = Path("data/index.heartbeat")
LIVE_STATUS_FILE = Path("data/index.live.json")
LIVE_STATUS_LOCK = threading.Lock()
live_status: Optional["LiveStatus"] = None


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


def setup_logging(config: CentralConfig) -> None:
    log_dir = config.logging.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "indexer.log"
    logging.basicConfig(
        level=getattr(logging, config.logging.level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )


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

    with db.get_conn() as conn:
        run_id = db.record_index_run_start(conn, start_time)
        existing_meta = db.list_existing_meta(conn)
        save_run_id(run_id)

    root_entries = config.paths.roots
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

    to_process: List[Tuple[Path, str]] = []
    for root, source in root_entries:
        if not root.exists():
            logger.error("Wurzelpfad nicht gefunden: %s", root)
            counters["errors"] += 1
            continue
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                path = Path(dirpath) / name
                if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    to_process.append((path, path, source))

    init_live_status(run_id, start_time, len(to_process))

    work_queue: "queue.Queue[Optional[Dict]]" = queue.Queue(maxsize=200)
    scanned_paths: set[str] = set()
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
        local_existing = dict(existing_meta)
        nonlocal scanned_paths
        try:
            while True:
                item = work_queue.get()
                if item is None:
                    break
                kind = item.get("type")
                if kind == "error":
                    counters["scanned"] += 1
                    counters["skipped"] += 1
                    scanned_paths.add(item["path"])
                    try:
                        db.record_file_error(
                            conn,
                            run_id=run_id,
                            path=item["path"],
                            error_type=item["error_type"],
                            message=item["message"],
                            created_at=datetime.now(timezone.utc).isoformat(),
                        )
                    finally:
                        counters["errors"] += 1
                elif kind == "unchanged":
                    counters["scanned"] += 1
                    counters["skipped"] += 1
                    scanned_paths.add(item["path"])
                elif kind == "document":
                    meta: DocumentMeta = item["meta"]
                    counters["scanned"] += 1
                    scanned_paths.add(meta.path)
                    existing = local_existing.get(meta.path)
                    if existing and existing[0] == meta.size_bytes and existing[1] == meta.mtime:
                        counters["skipped"] += 1
                        continue
                    try:
                        db.upsert_document(conn, meta)
                        local_existing[meta.path] = (meta.size_bytes, meta.mtime)
                        if existing:
                            counters["updated"] += 1
                        else:
                            counters["added"] += 1
                    except Exception as exc:
                        try:
                            db.record_file_error(
                                conn,
                                run_id=run_id,
                                path=meta.path,
                                error_type=type(exc).__name__,
                                message=str(exc),
                                created_at=datetime.now(timezone.utc).isoformat(),
                            )
                        finally:
                            counters["errors"] += 1
                        # Attempt to reopen connection if broken
                        try:
                            conn.close()
                        except Exception:
                            pass
                        conn = db.connect()
                work_queue.task_done()
                try:
                    conn.commit()
                except Exception:
                    pass
                flush_live_status(item.get("path") if item else None)
        finally:
            conn.close()

    writer_thread = threading.Thread(target=writer, daemon=True)
    writer_thread.start()

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
        existing = existing_meta.get(str(original_path))
        if existing and existing[0] == meta.size_bytes and existing[1] == meta.mtime:
            work_queue.put({"type": "unchanged", "path": str(original_path)})
            return

        try:
            fill_content(meta, real_path, ext)
            if stop_event.is_set():
                return
            work_queue.put({"type": "document", "meta": meta})
        except Exception as exc:
            logger.error("Fehler bei %s: %s", original_path, exc)
            work_queue.put(
                {
                    "type": "error",
                    "path": str(original_path),
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        finally:
            touch_heartbeat()

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.indexer.worker_count) as pool:
        futures = [
            pool.submit(process_file_task, real_path, original_path, source)
            for real_path, original_path, source in to_process
        ]
        concurrent.futures.wait(futures)

    work_queue.put(None)
    writer_thread.join()
    flush_live_status(force=True)

    with db.get_conn() as conn:
        existing_paths = db.list_paths_by_sources(conn, [src for _, src in root_entries])
        missing = set(existing_paths) - set(scanned_paths)
        removed_count = db.remove_documents_by_paths(conn, missing)
        counters["removed"] = removed_count

    status = "stopped" if stop_event.is_set() else ("completed" if counters["errors"] == 0 else "completed_with_errors")
    update_live_status(counters, status=status, finished=True)
    with db.get_conn() as conn:
        db.record_index_run_finish(
            conn,
            run_id,
            datetime.now(timezone.utc).isoformat(),
            status,
            counters["scanned"],
            counters["added"],
            counters["updated"],
            counters["removed"],
            counters["errors"],
            None,
        )
    clear_run_id()
    send_report_if_configured(config, counters, status)
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


def process_file(real_path: Path, original_path: Path, source: str, config: CentralConfig, run_id: int) -> Dict[str, str]:
    try:
        stat = real_path.stat()
    except FileNotFoundError:
        return {"status": "error", "path": str(original_path)}

    max_size = config.indexer.max_file_size_mb
    if max_size and stat.st_size > max_size * 1024 * 1024:
        logger.info("Übersprungen (zu groß): %s", original_path)
        return {"status": "skipped", "path": str(original_path)}

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
        with db.get_conn() as conn:
            existing = db.get_document_by_path(conn, str(original_path))
            if existing and existing["size_bytes"] == stat.st_size and existing["mtime"] == stat.st_mtime:
                return {"status": "unchanged", "path": str(original_path)}

        fill_content(meta, real_path, ext)
        status = "added"
        with db.get_conn() as conn:
            if existing:
                status = "updated"
            db.upsert_document(conn, meta)
        return {"status": status, "path": str(original_path)}
    except Exception as exc:  # pragma: no cover - Schutz gegen Einzeldateifehler
        logger.error("Fehler bei %s: %s", original_path, exc)
        with db.get_conn() as conn:
            db.record_file_error(
                conn,
                run_id=run_id,
                path=str(original_path),
                error_type=type(exc).__name__,
                message=str(exc),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        return {"status": "error", "path": str(original_path)}


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
    else:
        meta.content = ""
        meta.title_or_subject = meta.filename


def get_owner(stat) -> Optional[str]:
    try:
        import pwd

        return pwd.getpwuid(stat.st_uid).pw_name
    except Exception:
        return None


def send_report_if_configured(config: CentralConfig, counters: Dict[str, int], status: str) -> None:
    smtp = config.smtp
    if not smtp:
        logger.info("Kein SMTP konfiguriert, überspringe Report")
        return
    subject = f"Indexlauf {status}"
    body = (
        f"Status: {status}\n"
        f"Gescannt: {counters['scanned']}\n"
        f"Hinzugefügt: {counters['added']}\n"
        f"Aktualisiert: {counters['updated']}\n"
        f"Entfernt: {counters['removed']}\n"
        f"Fehler: {counters['errors']}\n"
    )
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp.sender
    msg["To"] = ", ".join([str(r) for r in smtp.recipients])
    msg.set_content(body)

    try:
        with smtplib.SMTP(smtp.host, smtp.port, timeout=10) as server:
            if smtp.use_tls:
                server.starttls()
            if smtp.username:
                server.login(smtp.username, smtp.password or "")
            server.send_message(msg)
        logger.info("Report gesendet an %s", smtp.recipients)
    except Exception as exc:  # pragma: no cover
        logger.error("Report-Versand fehlgeschlagen: %s", exc)


if __name__ == "__main__":  # pragma: no cover
    from app.config_loader import load_config

    cfg = load_config()
    result = run_index_lauf(cfg)
    print("Indexlauf abgeschlossen:", result)
