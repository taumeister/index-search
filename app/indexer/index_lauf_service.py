import concurrent.futures
import logging
import os
import smtplib
from email.message import EmailMessage
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.config_loader import CentralConfig
from app.db import datenbank as db
from app.db.datenbank import DocumentMeta
from app.indexer import extractors

logger = logging.getLogger("indexer")


SUPPORTED_EXTENSIONS = {".pdf", ".rtf", ".msg", ".txt"}


def setup_logging(config: CentralConfig) -> None:
    log_dir = config.logging.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "indexer.log"
    logging.basicConfig(
        level=getattr(logging, config.logging.level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )


def run_index_lauf(config: CentralConfig) -> Dict[str, int]:
    db.init_db()
    setup_logging(config)

    start_time = datetime.now(timezone.utc).isoformat()
    counters = {"scanned": 0, "added": 0, "updated": 0, "removed": 0, "errors": 0}

    with db.get_conn() as conn:
        run_id = db.record_index_run_start(conn, start_time)

    root_entries = config.paths.roots
    if not root_entries:
        logger.warning("Keine roots konfiguriert, Indexlauf beendet")
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

    scanned_paths = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.indexer.worker_count) as pool:
        futures = [
            pool.submit(process_file, real_path, original_path, source, config, run_id)
            for real_path, original_path, source in to_process
        ]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            counters["scanned"] += 1
            if result["status"] == "added":
                counters["added"] += 1
            elif result["status"] == "updated":
                counters["updated"] += 1
            elif result["status"] == "unchanged":
                pass
            else:
                counters["errors"] += 1
            scanned_paths.append(result["path"])

    # Entferne fehlende Dateien
    with db.get_conn() as conn:
        existing_paths = db.list_paths_by_sources(conn, [src for _, src in root_entries])
        missing = set(existing_paths) - set(scanned_paths)
        removed_count = db.remove_documents_by_paths(conn, missing)
        counters["removed"] = removed_count

    status = "completed" if counters["errors"] == 0 else "completed_with_errors"
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
    send_report_if_configured(config, counters, status)
    return counters


def process_file(real_path: Path, original_path: Path, source: str, config: CentralConfig, run_id: int) -> Dict[str, str]:
    try:
        stat = real_path.stat()
    except FileNotFoundError:
        return {"status": "error", "path": str(original_path)}

    max_size = config.indexer.max_file_size_mb
    if max_size and stat.st_size > max_size * 1024 * 1024:
        logger.info("Übersprungen (zu groß): %s", path)
        return {"status": "skipped", "path": str(path)}

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
