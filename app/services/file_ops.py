import errno
import json
import logging
import os
import shutil
import sqlite3
import threading
import time
from uuid import uuid4
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from app.db import datenbank as db
from app.db.datenbank import QuarantineEntry

logger = logging.getLogger(__name__)


@dataclass
class SourceInfo:
    label: str
    root: Path
    quarantine_dir: Path
    ready: bool


@dataclass
class QuarantineSettings:
    retention_days: int = 30
    cleanup_schedule: str = "daily"
    cleanup_dry_run: bool = False


class FileOpError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


AUDIT_LOG = Path("data/audit/file_ops.jsonl")
_sources: Dict[str, SourceInfo] = {}
_settings = QuarantineSettings()
_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_cleanup_thread: Optional[threading.Thread] = None
_cleanup_stop = threading.Event()


def _canonical(path: Path) -> Path:
    try:
        return path.resolve()
    except Exception:
        return Path(os.path.abspath(path))


def check_within_root(path: Path, root: Path) -> bool:
    try:
        canonical_path = _canonical(path)
        canonical_root = _canonical(root)
        return canonical_path.is_relative_to(canonical_root)
    except Exception:
        return False


def _normalize_rel_path(raw: str) -> Path:
    text = (raw or "").replace("\\", "/").strip()
    if text.startswith("/"):
        text = text[1:]
    parts = [p for p in text.split("/") if p not in ("", ".")]
    for part in parts:
        if part in ("", ".", "..") or "\x00" in part or "/" in part or "\\" in part:
            raise FileOpError("Ungültiger Pfad", status_code=400)
    return Path("/".join(parts)) if parts else Path()


def _audit(entry: Dict[str, object]) -> None:
    payload = dict(entry) if isinstance(entry, dict) else {}
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        logger.debug("Audit-Log schreiben fehlgeschlagen", exc_info=True)


def ensure_quarantine(root: Path) -> Tuple[Path, bool]:
    canonical_root = _canonical(root)
    quarantine_dir = canonical_root / ".quarantine"
    try:
        quarantine_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return quarantine_dir, False
    test_file = quarantine_dir / ".rw_test"
    try:
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return quarantine_dir, True
    except Exception:
        try:
            test_file.unlink(missing_ok=True)
        except Exception:
            pass
        return quarantine_dir, False


def init_sources(root_entries: List[Tuple[Path, str]]) -> None:
    global _sources
    _sources = {}
    for root, label in root_entries:
        quarantine_dir, ready = ensure_quarantine(root)
        _sources[label] = SourceInfo(label=label, root=_canonical(root), quarantine_dir=quarantine_dir, ready=ready)


def refresh_quarantine_state() -> None:
    for label, info in list(_sources.items()):
        quarantine_dir, ready = ensure_quarantine(info.root)
        _sources[label] = SourceInfo(label=label, root=info.root, quarantine_dir=quarantine_dir, ready=ready)


def apply_settings(settings: Optional[QuarantineSettings]) -> None:
    global _settings
    if settings is None:
        return
    _settings = QuarantineSettings(
        retention_days=max(0, int(getattr(settings, "retention_days", _settings.retention_days))),
        cleanup_schedule=(getattr(settings, "cleanup_schedule", _settings.cleanup_schedule) or "daily").strip().lower(),
        cleanup_dry_run=bool(getattr(settings, "cleanup_dry_run", _settings.cleanup_dry_run)),
    )


def get_status() -> Dict[str, object]:
    ready_sources = [
        {"label": info.label, "root": str(info.root), "quarantine_dir": str(info.quarantine_dir), "ready": info.ready}
        for info in _sources.values()
        if info.ready
    ]
    return {
        "file_ops_enabled": any(info.ready for info in _sources.values()),
        "quarantine_ready_sources": ready_sources,
        "quarantine_retention_days": _settings.retention_days,
        "quarantine_cleanup_schedule": _settings.cleanup_schedule,
        "quarantine_cleanup_dry_run": _settings.cleanup_dry_run,
    }


@contextmanager
def _locked_paths(paths: Iterable[Path]):
    keys = sorted({str(_canonical(p)) for p in paths if p})
    locks: List[threading.Lock] = []
    with _locks_guard:
        for key in keys:
            lock = _locks.get(key)
            if lock is None:
                lock = threading.Lock()
                _locks[key] = lock
            locks.append(lock)
    for lock in locks:
        lock.acquire()
    try:
        yield
    finally:
        for lock in reversed(locks):
            try:
                lock.release()
            except Exception:
                pass


def _copy_file_with_fsync(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as fsrc, dest.open("wb") as fdst:
        shutil.copyfileobj(fsrc, fdst, length=1024 * 1024)
        fdst.flush()
        os.fsync(fdst.fileno())


def _move_file(src: Path, dest: Path) -> None:
    try:
        os.replace(src, dest)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    _copy_file_with_fsync(src, dest)
    os.unlink(src)


def resolve_doc(doc_id: int) -> Optional[Dict[str, object]]:
    with db.get_conn() as conn:
        row = db.get_document(conn, doc_id)
    if not row:
        return None
    data = dict(row)
    try:
        path_value = data.get("path")
        if path_value:
            data["abs_path"] = _canonical(Path(path_value))
        else:
            data["abs_path"] = None
    except Exception:
        data["abs_path"] = None
    return data


def list_directories(source_label: str, rel_path: str = "", limit: int = 500) -> Dict[str, object]:
    info = _resolve_source(source_label)
    _assert_quarantine_ready(info)
    safe_rel = _normalize_rel_path(rel_path)
    base_dir = _canonical(info.root / safe_rel)
    if not check_within_root(base_dir, info.root):
        raise FileOpError("Pfad liegt außerhalb der Quelle", status_code=400)
    if not base_dir.exists():
        raise FileOpError("Pfad nicht gefunden", status_code=404)
    if not base_dir.is_dir():
        raise FileOpError("Pfad ist kein Verzeichnis", status_code=400)

    entries: List[Dict[str, object]] = []
    try:
        with os.scandir(base_dir) as it:
            for entry in it:
                if len(entries) >= limit:
                    break
                try:
                    if not entry.is_dir():
                        continue
                    if entry.name in (".", "..", ".quarantine"):
                        continue
                    rel_child = (safe_rel / entry.name).as_posix()
                    has_children = False
                    try:
                        with os.scandir(entry.path) as sub_it:
                            for sub in sub_it:
                                if sub.is_dir():
                                    has_children = True
                                    break
                    except Exception:
                        has_children = False
                    entries.append({"name": entry.name, "path": rel_child, "has_children": has_children})
                except Exception:
                    continue
    except FileNotFoundError:
        raise FileOpError("Pfad nicht gefunden", status_code=404)
    entries.sort(key=lambda e: e["name"].lower())
    return {"source": info.label, "path": safe_rel.as_posix(), "entries": entries}


def _resolve_source(label: str, fallback_root: Optional[str] = None) -> SourceInfo:
    info = _sources.get(label)
    if info:
        quarantine_dir, ready = ensure_quarantine(info.root)
        info = SourceInfo(label=label, root=info.root, quarantine_dir=quarantine_dir, ready=ready)
        _sources[label] = info
        return info
    if not fallback_root:
        raise FileOpError("Quelle nicht verfügbar", status_code=400)
    root_path = _canonical(Path(fallback_root))
    quarantine_dir, ready = ensure_quarantine(root_path)
    info = SourceInfo(label=label, root=root_path, quarantine_dir=quarantine_dir, ready=ready)
    _sources[label] = info
    return info


def _assert_quarantine_ready(info: SourceInfo) -> None:
    if not info.ready:
        raise FileOpError("Quarantäne nicht verfügbar", status_code=400)


def _validate_new_filename(new_name: str, current_name: str, current_suffix: str) -> str:
    candidate = (new_name or "").strip()
    if not candidate:
        raise FileOpError("Ungültiger Name", status_code=400)
    if candidate in {".", ".."}:
        raise FileOpError("Ungültiger Name", status_code=400)
    if "/" in candidate or "\\" in candidate or "\x00" in candidate:
        raise FileOpError("Ungültiger Name", status_code=400)
    if Path(candidate).name != candidate:
        raise FileOpError("Ungültiger Name", status_code=400)
    current_ext = (current_suffix or "").lower()
    new_ext = Path(candidate).suffix.lower()
    if current_ext != new_ext:
        raise FileOpError("Dateiendung darf nicht geändert werden", status_code=400)
    if candidate == current_name:
        raise FileOpError("Name unverändert", status_code=400)
    return candidate


def rename_file(doc_id: int, new_name: str, actor: str = "admin") -> Dict[str, object]:
    doc = resolve_doc(doc_id)
    if not doc:
        raise FileOpError("Dokument nicht gefunden", status_code=404)

    source_label = doc.get("source") or ""
    info = _resolve_source(source_label)
    _assert_quarantine_ready(info)

    abs_path = doc.get("abs_path")
    if not isinstance(abs_path, Path):
        raise FileOpError("Pfad ungültig", status_code=400)
    if not check_within_root(abs_path, info.root):
        raise FileOpError("Pfad liegt außerhalb der Quelle", status_code=400)
    if not abs_path.exists():
        raise FileOpError("Datei nicht gefunden", status_code=404)

    validated_name = _validate_new_filename(new_name, abs_path.name, abs_path.suffix)
    target_path = _canonical(abs_path.parent / validated_name)
    if abs_path.parent != target_path.parent:
        raise FileOpError("Pfad liegt außerhalb der Quelle", status_code=400)
    if not check_within_root(target_path, info.root):
        raise FileOpError("Pfad liegt außerhalb der Quelle", status_code=400)
    if target_path.exists():
        raise FileOpError("Name schon vorhanden", status_code=409)

    tmp_path = target_path.with_name(f"{target_path.name}.tmp_rename_{uuid4().hex}")
    date_folder = datetime.now().strftime("%Y-%m-%d")
    backup_dir = info.quarantine_dir / date_folder / ".rename_backup"
    backup_path = backup_dir / f"{doc_id}__{abs_path.name}"

    audit_base = {
        "action": "rename",
        "actor": actor or "admin",
        "doc_id": doc_id,
        "source": source_label,
        "source_root": str(info.root),
        "old_path": str(abs_path),
        "new_path": str(target_path),
        "backup_path": str(backup_path),
    }

    title_update: Optional[str] = None
    try:
        with db.get_conn() as conn:
            title = db.get_document_title(conn, doc_id)
        if title is None and abs_path.suffix.lower() != ".msg":
            title_update = validated_name
        elif title == abs_path.name and abs_path.suffix.lower() != ".msg":
            title_update = validated_name
    except Exception:
        title_update = None

    tmp_created = False
    target_created = False
    backup_moved = False

    def _rollback() -> None:
        if tmp_created:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        if not backup_moved and target_created:
            try:
                target_path.unlink(missing_ok=True)
            except Exception:
                pass
        if backup_moved:
            try:
                if target_path.exists():
                    target_path.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                _move_file(backup_path, abs_path)
            except Exception:
                pass

    with _locked_paths([abs_path, target_path, backup_path]):
        try:
            _copy_file_with_fsync(abs_path, tmp_path)
            tmp_created = True
            try:
                shutil.copystat(abs_path, tmp_path, follow_symlinks=True)
            except Exception:
                pass
            os.replace(tmp_path, target_path)
            target_created = True

            backup_dir.mkdir(parents=True, exist_ok=True)
            _move_file(abs_path, backup_path)
            backup_moved = True

            stat_result = target_path.stat()
            try:
                with db.get_conn() as conn:
                    updated = db.update_document_metadata(
                        conn,
                        doc_id,
                        path=str(target_path),
                        filename=target_path.name,
                        extension=target_path.suffix.lower(),
                        size_bytes=stat_result.st_size,
                        ctime=stat_result.st_ctime,
                        mtime=stat_result.st_mtime,
                        atime=getattr(stat_result, "st_atime", None),
                        title_or_subject=title_update,
                    )
            except sqlite3.IntegrityError:
                raise FileOpError("Name schon vorhanden", status_code=409)
            if not updated:
                raise FileOpError("Dokument nicht gefunden", status_code=404)
        except FileOpError as exc:
            _rollback()
            _audit({**audit_base, "status": "error", "error": str(exc)})
            raise
        except Exception as exc:
            _rollback()
            _audit({**audit_base, "status": "error", "error": str(exc)})
            raise
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    _audit({**audit_base, "status": "ok"})
    return {
        "doc_id": doc_id,
        "source": source_label,
        "old_path": str(abs_path),
        "new_path": str(target_path),
        "backup_path": str(backup_path),
        "updated_in_index": True,
        "display_name": target_path.name,
        "display_path": str(target_path),
    }


def move_file(doc_id: int, target_dir: str, actor: str = "admin") -> Dict[str, object]:
    doc = resolve_doc(doc_id)
    if not doc:
        raise FileOpError("Dokument nicht gefunden", status_code=404)

    source_label = doc.get("source") or ""
    info = _resolve_source(source_label)
    _assert_quarantine_ready(info)

    abs_path = doc.get("abs_path")
    if not isinstance(abs_path, Path):
        raise FileOpError("Pfad ungültig", status_code=400)
    if not check_within_root(abs_path, info.root):
        raise FileOpError("Pfad liegt außerhalb der Quelle", status_code=400)
    if not abs_path.exists():
        raise FileOpError("Datei nicht gefunden", status_code=404)

    safe_target_dir = _normalize_rel_path(target_dir)
    target_base = _canonical(info.root / safe_target_dir)
    if not check_within_root(target_base, info.root):
        raise FileOpError("Ziel liegt außerhalb der Quelle", status_code=400)
    if not target_base.exists() or not target_base.is_dir():
        raise FileOpError("Zielordner nicht gefunden", status_code=404)
    if str(target_base).startswith(str(info.quarantine_dir)):
        raise FileOpError("Quarantäne kann nicht als Ziel genutzt werden", status_code=400)

    target_path = _canonical(target_base / abs_path.name)
    if not check_within_root(target_path, info.root):
        raise FileOpError("Ziel liegt außerhalb der Quelle", status_code=400)
    if target_path == abs_path:
        raise FileOpError("Ziel entspricht dem aktuellen Ort", status_code=400)
    if target_path.exists():
        raise FileOpError("Ziel existiert bereits", status_code=409)

    audit_base = {
        "action": "move",
        "actor": actor or "admin",
        "doc_id": doc_id,
        "source": source_label,
        "source_root": str(info.root),
        "old_path": str(abs_path),
        "new_path": str(target_path),
    }

    moved = False
    with _locked_paths([abs_path, target_path]):
        try:
            target_base.mkdir(parents=True, exist_ok=True)
            _move_file(abs_path, target_path)
            moved = True
            stat_result = target_path.stat()
            with db.get_conn() as conn:
                updated = db.update_document_metadata(
                    conn,
                    doc_id,
                    path=str(target_path),
                    filename=target_path.name,
                    extension=target_path.suffix.lower(),
                    size_bytes=stat_result.st_size,
                    ctime=stat_result.st_ctime,
                    mtime=stat_result.st_mtime,
                    atime=getattr(stat_result, "st_atime", None),
                    title_or_subject=None,
                )
            if not updated:
                raise FileOpError("Dokument nicht gefunden", status_code=404)
        except FileOpError as exc:
            if moved and not abs_path.exists() and target_path.exists():
                try:
                    _move_file(target_path, abs_path)
                except Exception:
                    pass
            _audit({**audit_base, "status": "error", "error": str(exc)})
            raise
        except Exception as exc:
            if moved and not abs_path.exists() and target_path.exists():
                try:
                    _move_file(target_path, abs_path)
                except Exception:
                    pass
            _audit({**audit_base, "status": "error", "error": str(exc)})
            raise

    _audit({**audit_base, "status": "ok"})
    return {
        "doc_id": doc_id,
        "source": source_label,
        "old_path": str(abs_path),
        "new_path": str(target_path),
        "display_name": target_path.name,
        "display_path": str(target_path),
    }


def quarantine_delete(doc_id: int, actor: str = "admin") -> Dict[str, object]:
    doc = resolve_doc(doc_id)
    if not doc:
        raise FileOpError("Dokument nicht gefunden", status_code=404)

    source_label = doc.get("source") or ""
    info = _resolve_source(source_label)
    _assert_quarantine_ready(info)

    abs_path = doc.get("abs_path")
    if not isinstance(abs_path, Path):
        raise FileOpError("Pfad ungültig", status_code=400)
    if not check_within_root(abs_path, info.root):
        raise FileOpError("Pfad liegt außerhalb der Quelle", status_code=400)
    if not abs_path.exists():
        raise FileOpError("Datei nicht gefunden", status_code=404)

    date_folder = datetime.now().strftime("%Y-%m-%d")
    target_dir = info.quarantine_dir / date_folder
    target_path = target_dir / f"{doc_id}__{abs_path.name}"
    if target_path.exists():
        raise FileOpError("Quarantäne-Ziel existiert bereits", status_code=409)

    audit_base = {
        "actor": actor or "admin",
        "doc_id": doc_id,
        "source": source_label,
        "source_root": str(info.root),
        "original_path": str(abs_path),
        "quarantine_path": str(target_path),
        "action": "quarantine_delete",
    }
    entry_id: Optional[int] = None
    moved = False
    with _locked_paths([abs_path, target_path]):
        target_dir.mkdir(parents=True, exist_ok=True)
        entry = QuarantineEntry(
            doc_id=doc_id,
            source=source_label,
            source_root=str(info.root),
            original_path=str(abs_path),
            quarantine_path=str(target_path),
            original_filename=abs_path.name,
            moved_at=datetime.now(timezone.utc).isoformat(),
            actor=actor or "admin",
            size_bytes=doc.get("size_bytes"),
        )
        try:
            with db.get_conn() as conn:
                entry_id = db.insert_quarantine_entry(conn, entry)
                db.remove_document_by_id(conn, doc_id)
                _move_file(abs_path, target_path)
                moved = True
        except FileOpError:
            _audit({**audit_base, "status": "error", "error": "validation"})
            raise
        except Exception as exc:
            if moved and target_path.exists() and not abs_path.exists():
                try:
                    _move_file(target_path, abs_path)
                except Exception:
                    pass
            _audit({**audit_base, "status": "error", "error": str(exc)})
            raise

    _audit({**audit_base, "status": "ok", "entry_id": entry_id})
    return {
        "doc_id": doc_id,
        "source": source_label,
        "original_path": str(abs_path),
        "quarantine_path": str(target_path),
        "removed_from_index": True,
        "entry_id": entry_id,
    }


def _load_entry(entry_id: int) -> Dict[str, object]:
    with db.get_conn() as conn:
        row = db.get_quarantine_entry(conn, entry_id)
    if not row:
        raise FileOpError("Quarantäne-Eintrag nicht gefunden", status_code=404)
    return dict(row)


def _validate_quarantine_entry(entry: Dict[str, object]) -> None:
    status = (entry.get("status") or "").lower()
    if status != "quarantined":
        raise FileOpError("Eintrag ist nicht mehr in Quarantäne", status_code=400)


def list_quarantine_entries(
    source: Optional[str] = None,
    text: Optional[str] = None,
    max_age_days: Optional[int] = None,
) -> List[Dict[str, object]]:
    with db.get_conn() as conn:
        rows = db.list_quarantine_entries(conn, status="quarantined", source=source)
    now = datetime.now(timezone.utc)
    results: List[Dict[str, object]] = []
    for row in rows:
        entry = dict(row)
        moved_at = entry.get("moved_at")
        if max_age_days is not None and moved_at:
            try:
                moved_dt = datetime.fromisoformat(moved_at)
                age_days = (now - moved_dt).total_seconds() / 86400
                if age_days > max_age_days:
                    continue
            except Exception:
                pass
        if text:
            needle = text.lower()
            hay = f"{entry.get('original_filename','')} {entry.get('original_path','')}".lower()
            if needle not in hay:
                continue
        results.append(entry)
    return results


def quarantine_restore(entry_id: int, actor: str = "admin") -> Dict[str, object]:
    entry = _load_entry(entry_id)
    _validate_quarantine_entry(entry)
    info = _resolve_source(entry.get("source") or "", fallback_root=entry.get("source_root"))
    _assert_quarantine_ready(info)

    quarantine_path = _canonical(Path(entry["quarantine_path"]))
    if not check_within_root(quarantine_path, info.quarantine_dir):
        raise FileOpError("Ungültiger Quarantänepfad", status_code=400)
    if not quarantine_path.exists():
        raise FileOpError("Datei in Quarantäne nicht gefunden", status_code=404)

    original_path = _canonical(Path(entry["original_path"]))
    if not check_within_root(original_path, info.root):
        raise FileOpError("Originalpfad liegt außerhalb der Quelle", status_code=400)

    target_path = original_path
    if target_path.exists():
        suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        target_path = target_path.with_name(f"{target_path.name}_restored_{suffix}")

    audit_base = {
        "action": "restore",
        "actor": actor or "admin",
        "entry_id": entry_id,
        "source": info.label,
        "source_root": str(info.root),
        "original_path": str(original_path),
        "quarantine_path": str(quarantine_path),
        "target_path": str(target_path),
    }

    with _locked_paths([quarantine_path, target_path]):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        _move_file(quarantine_path, target_path)
        try:
            os.utime(target_path, None)
        except Exception:
            pass
        try:
            with db.get_conn() as conn:
                db.mark_quarantine_restored(conn, entry_id, str(target_path), datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            _audit({**audit_base, "status": "error", "error": str(exc)})
            raise

    _audit({**audit_base, "status": "ok"})
    return {
        "entry_id": entry_id,
        "restored_path": str(target_path),
        "source": info.label,
    }


def quarantine_hard_delete(entry_id: int, actor: str = "admin") -> Dict[str, object]:
    entry = _load_entry(entry_id)
    _validate_quarantine_entry(entry)
    info = _resolve_source(entry.get("source") or "", fallback_root=entry.get("source_root"))
    _assert_quarantine_ready(info)

    quarantine_path = _canonical(Path(entry["quarantine_path"]))
    if not check_within_root(quarantine_path, info.quarantine_dir):
        raise FileOpError("Ungültiger Quarantänepfad", status_code=400)

    audit_base = {
        "action": "hard_delete",
        "actor": actor or "admin",
        "entry_id": entry_id,
        "source": info.label,
        "source_root": str(info.root),
        "quarantine_path": str(quarantine_path),
    }

    with _locked_paths([quarantine_path]):
        if not quarantine_path.exists():
            raise FileOpError("Datei bereits entfernt", status_code=404)
        try:
            quarantine_path.unlink()
        except Exception as exc:
            _audit({**audit_base, "status": "error", "error": str(exc)})
            raise
        try:
            with db.get_conn() as conn:
                db.mark_quarantine_hard_deleted(conn, entry_id, datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            _audit({**audit_base, "status": "error", "error": str(exc)})
            raise

    _audit({**audit_base, "status": "ok"})
    return {"entry_id": entry_id, "deleted": True}


def _parse_folder_age_days(path: Path, now: datetime) -> Optional[float]:
    try:
        folder_name = path.parent.name
        dt = datetime.fromisoformat(folder_name)
        delta = now - dt
        return max(0.0, delta.total_seconds() / 86400)
    except Exception:
        return None


def run_cleanup_now(now: Optional[datetime] = None) -> Dict[str, int]:
    refresh_quarantine_state()
    now = now or datetime.now(timezone.utc)
    retention_days = max(0, _settings.retention_days)
    summary = {"deleted": 0, "dry_run": 0, "skipped": 0, "errors": 0}
    for info in _sources.values():
        if not info.ready:
            continue
        base = info.quarantine_dir
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.name.startswith(".rw_test"):
                continue
            if not check_within_root(path, base):
                _audit(
                    {
                        "action": "cleanup_delete",
                        "source_root": str(info.root),
                        "quarantine_path": str(path),
                        "age_days": None,
                        "status": "error",
                        "error": "outside_quarantine",
                    }
                )
                summary["errors"] += 1
                continue
            try:
                stat = path.stat()
            except FileNotFoundError:
                summary["errors"] += 1
                continue
            except Exception:
                summary["errors"] += 1
                continue
            age_mtime = max(0.0, (now - datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)).total_seconds() / 86400)
            age_folder = _parse_folder_age_days(path, now)
            age_days = max(age_mtime, age_folder) if age_folder is not None else age_mtime
            if age_days < retention_days:
                summary["skipped"] += 1
                continue

            audit_base = {
                "action": "cleanup_delete",
                "source_root": str(info.root),
                "quarantine_path": str(path),
                "age_days": age_days,
            }
            with _locked_paths([path]):
                if _settings.cleanup_dry_run:
                    _audit({**audit_base, "status": "dry_run"})
                    summary["dry_run"] += 1
                    continue
                try:
                    path.unlink(missing_ok=True)
                    with db.get_conn() as conn:
                        entry = db.get_quarantine_entry_by_path(conn, str(path))
                        if entry:
                            db.mark_quarantine_cleanup_deleted(conn, entry["id"], datetime.now(timezone.utc).isoformat())
                    _audit({**audit_base, "status": "ok"})
                    summary["deleted"] += 1
                except Exception as exc:
                    _audit({**audit_base, "status": "error", "error": str(exc)})
                    summary["errors"] += 1
                    continue
            try:
                parent = path.parent
                while parent != base and parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
            except Exception:
                pass
    return summary


def _cleanup_interval_seconds() -> int:
    schedule = (_settings.cleanup_schedule or "daily").strip().lower()
    if schedule in {"off", "disabled", "none"}:
        return 0
    if schedule in {"hourly", "1h"}:
        return 3600
    return 24 * 3600


def start_cleanup_scheduler() -> None:
    global _cleanup_thread
    interval = _cleanup_interval_seconds()
    if interval <= 0:
        return
    if _cleanup_thread and _cleanup_thread.is_alive():
        return
    if os.getenv("PYTEST_CURRENT_TEST"):
        return

    _cleanup_stop.clear()

    def worker():
        while not _cleanup_stop.is_set():
            try:
                run_cleanup_now()
            except Exception as exc:
                logger.error("Quarantäne-Cleanup fehlgeschlagen: %s", exc)
            _cleanup_stop.wait(interval)

    _cleanup_thread = threading.Thread(target=worker, daemon=True)
    _cleanup_thread.start()


def stop_cleanup_scheduler() -> None:
    _cleanup_stop.set()
    if _cleanup_thread and _cleanup_thread.is_alive():
        _cleanup_thread.join(timeout=2)
