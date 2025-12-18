import threading
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, Iterable

from app.config_loader import CentralConfig, load_config
from app.indexer.index_lauf_service import run_index_lauf, RUN_STATUS_FILE, HEARTBEAT_FILE, LIVE_STATUS_FILE
from app.db import datenbank as db
from app.services import readiness

logger = logging.getLogger(__name__)

index_lock = threading.Lock()


def check_sources_readiness_for_index(roots: Iterable[tuple[Path, str]]):
    roots_list = list(roots)
    try:
        with db.get_conn() as conn:
            labels = [label for _, label in roots_list]
            counts = db.count_documents_by_source(conn, labels)
            samples = db.get_sample_paths_by_source(conn, labels)
    except Exception:
        counts = {}
        samples = {}
    return readiness.check_sources_ready(roots_list, counts, samples)


def clear_index_files() -> None:
    base = Path(getattr(db, "DB_PATH", Path("data/index.db")))
    candidates = [
        base,
        base.with_suffix(base.suffix + "-wal"),
        base.with_suffix(base.suffix + "-shm"),
        RUN_STATUS_FILE,
        HEARTBEAT_FILE,
        LIVE_STATUS_FILE,
    ]
    for p in candidates:
        try:
            if p.exists():
                p.unlink()
        except Exception as exc:
            logger.error("Index-Datei konnte nicht gelöscht werden: %s", exc)
            raise


def start_index_run(
    full_reset: bool = False,
    cfg_override: Optional[CentralConfig] = None,
    roots_override: Optional[Iterable[tuple[Path, str]]] = None,
    reason: str = "manual",
    on_finish: Optional[Callable[[str, datetime, datetime, Optional[str]], None]] = None,
    resolve_roots: Optional[Callable[[CentralConfig], Iterable[tuple[Path, str]]]] = None,
) -> str:
    """
    Startet einen Indexlauf in einem eigenen Thread und verhindert parallele Läufe.
    on_finish(status, started_at, finished_at, error_msg)
    """
    if not index_lock.acquire(blocking=False):
        return "busy"

    start_ts = datetime.now(timezone.utc)

    def runner():
        status = "completed"
        err: Optional[str] = None
        try:
            cfg = cfg_override or load_config()
            try:
                roots_iter = roots_override or (resolve_roots(cfg) if resolve_roots else [])
                cfg.paths.roots = list(roots_iter)
                if not cfg.paths.roots:
                    raise ValueError("Keine aktiven Quellen konfiguriert")
            except Exception as exc:
                logger.error("Indexlauf abgebrochen (%s): %s", reason, exc)
                status = "error"
                err = str(exc)
                return
            if full_reset:
                try:
                    clear_index_files()
                except Exception as exc:
                    logger.error("Reset fehlgeschlagen: %s", exc)
                    status = "error"
                    err = str(exc)
                    return
            run_index_lauf(cfg)
        except Exception as exc:
            status = "error"
            err = str(exc)
            logger.error("Indexlauf fehlgeschlagen (%s): %s", reason, exc)
        finally:
            finish_ts = datetime.now(timezone.utc)
            index_lock.release()
            if on_finish:
                try:
                    on_finish(status, start_ts, finish_ts, err)
                except Exception:
                    logger.exception("Auto-Index Status-Callback fehlgeschlagen")

    threading.Thread(target=runner, daemon=True).start()
    return "started"
