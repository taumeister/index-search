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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from app.db import datenbank as db
from app.db.datenbank import DocumentMeta, QuarantineEntry
from app import config_db
from app.services import readiness

logger = logging.getLogger(__name__)


@dataclass
class SourceInfo:
    label: str
    root: Path
    quarantine_dir: Path
    ready: bool
    issue: Optional[str] = None


@dataclass
class QuarantineSettings:
    retention_days: int = 30
    cleanup_schedule: str = "off"
    cleanup_dry_run: bool = False
    auto_purge_enabled: bool = False


@dataclass
class UploadSession:
    session_id: str
    source_label: str
    target_root: Path
    target_dir: Path
    quarantine_dir: Path
    staging_dir: Path
    total_files: int
    total_bytes: int
    uploaded_files: int = 0
    uploaded_bytes: int = 0
    import_count: int = 0
    import_total: int = 0
    overwrite_mode: str = "reject"
    stage: str = "init"
    error: Optional[str] = None
    expected_names: set[str] = field(default_factory=set)
    index_status: str = "idle"
    conflicts: list[str] = field(default_factory=list)


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
_upload_sessions: Dict[str, UploadSession] = {}
_upload_sessions_lock = threading.Lock()


def _canonical(path: Path) -> Path:
    return readiness._canonical(path)


def _assert_safe_root(root: Path) -> Path:
    canonical = _canonical(root)
    result = readiness.check_sources_ready([(canonical, canonical.name)])
    if result.ok:
        return canonical
    msg = result.message or "Netzlaufwerk nicht bereit"
    raise FileOpError(msg, status_code=503)


def _guard_path(target: Path, root: Path, allow_root: bool = False, must_exist: bool = True) -> Path:
    canonical_root = _assert_safe_root(root)
    canonical_target = _canonical(target)
    if must_exist and not canonical_target.exists():
        raise FileOpError("Pfad nicht gefunden", status_code=404)
    if not canonical_target.is_relative_to(canonical_root):
        raise FileOpError("Pfad liegt außerhalb der Quelle", status_code=400)
    if canonical_target == canonical_root and not allow_root:
        raise FileOpError("Operation auf Root verboten", status_code=400)
    return canonical_target


def safe_delete(target: Path, allowed_root: Path) -> Path:
    canonical_target = _guard_path(target, allowed_root, allow_root=False, must_exist=True)
    with _locked_paths([canonical_target]):
        canonical_target.unlink()
    return canonical_target


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


def _sanitize_upload_name(name: str) -> str:
    base = Path(name or "").name
    if not base or base in {".", ".."}:
        raise FileOpError("Ungültiger Dateiname", status_code=400)
    if "/" in base or "\\" in base or "\x00" in base:
        raise FileOpError("Ungültiger Dateiname", status_code=400)
    return base


def _unique_target_path(candidate: Path, root: Path) -> Path:
    base = candidate.stem
    suffix = candidate.suffix
    parent = candidate.parent
    idx = 1
    while True:
        alt = parent / f"{base}_upload_{idx}{suffix}"
        alt = _guard_path(alt, root, allow_root=False, must_exist=False)
        if not alt.exists():
            return alt
        idx += 1


def _get_upload_session(session_id: str) -> UploadSession:
    with _upload_sessions_lock:
        session = _upload_sessions.get(session_id)
    if not session:
        raise FileOpError("Upload-Session nicht gefunden", status_code=404)
    return session


def _store_session(session: UploadSession) -> None:
    with _upload_sessions_lock:
        _upload_sessions[session.session_id] = session


def _remove_session(session_id: str) -> None:
    with _upload_sessions_lock:
        _upload_sessions.pop(session_id, None)


def _audit(entry: Dict[str, object]) -> None:
    payload = dict(entry) if isinstance(entry, dict) else {}
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        logger.debug("Audit-Log schreiben fehlgeschlagen", exc_info=True)


def ensure_quarantine(root: Path, label: str = "") -> Tuple[Path, bool, Optional[str]]:
    canonical_root = _canonical(root)
    src_result = readiness.check_sources_ready(
        [(canonical_root, label or canonical_root.name)],
        existing_counts={},
        sample_paths={},
        require_non_empty=True,
    )
    if not src_result.ok:
        reason = src_result.issues[0].reason if src_result.issues else "Netzlaufwerk nicht bereit"
        return canonical_root / ".quarantine", False, reason
    try:
        if not canonical_root.is_dir():
            return canonical_root / ".quarantine", False, "Quelle nicht verfügbar (Mount fehlt)"
        if not any(canonical_root.iterdir()):
            return canonical_root / ".quarantine", False, "Quelle nicht verfügbar (leer/offline)"
    except Exception:
        return canonical_root / ".quarantine", False, "Quelle nicht verfügbar (Mount fehlt)"
    quarantine_dir = canonical_root / ".quarantine"
    if not quarantine_dir.exists():
        try:
            quarantine_dir.mkdir(parents=False, exist_ok=False)
        except Exception:
            return quarantine_dir, False, "Quarantäne nicht beschreibbar"
    q_result = readiness.check_quarantine_writable(quarantine_dir)
    if not q_result.ok:
        reason = q_result.issues[0].reason if q_result.issues else "Quarantäne nicht beschreibbar"
        return quarantine_dir, False, reason
    return quarantine_dir, True, None


def init_sources(root_entries: List[Tuple[Path, str]]) -> None:
    global _sources
    _sources = {}
    for root, label in root_entries:
        canonical_root = _canonical(root)
        quarantine_dir, ready, issue = ensure_quarantine(canonical_root, label)
        _sources[label] = SourceInfo(label=label, root=canonical_root, quarantine_dir=quarantine_dir, ready=ready, issue=issue)


def refresh_quarantine_state() -> None:
    active_roots: List[Tuple[Path, str]] = []
    try:
        base_raw = config_db.get_setting("base_data_root", "/data") or "/data"
        base = Path(base_raw).resolve()
        for path, label, _rid, active in config_db.list_roots(active_only=False):
            if not active:
                continue
            p = Path(path).resolve()
            try:
                p.relative_to(base)
            except ValueError:
                continue
            # Lass Root zu, auch wenn er gerade nicht existiert; readiness wird separat geprüft
            active_roots.append((p, label or p.name))
    except Exception:
        pass

    if active_roots:
        init_sources(active_roots)
    else:
        # leere oder ungültige DB-Roots -> bestehende Quellen als not ready markieren
        for label, info in list(_sources.items()):
            _sources[label] = SourceInfo(label=label, root=info.root, quarantine_dir=info.quarantine_dir, ready=False, issue=info.issue or "Netzlaufwerk nicht bereit")


def apply_settings(settings: Optional[QuarantineSettings]) -> None:
    global _settings
    if settings is None:
        return
    _settings = QuarantineSettings(
        retention_days=max(0, int(getattr(settings, "retention_days", _settings.retention_days))),
        cleanup_schedule=(getattr(settings, "cleanup_schedule", _settings.cleanup_schedule) or "off").strip().lower(),
        cleanup_dry_run=bool(getattr(settings, "cleanup_dry_run", _settings.cleanup_dry_run)),
        auto_purge_enabled=bool(getattr(settings, "auto_purge_enabled", _settings.auto_purge_enabled)),
    )


def get_status() -> Dict[str, object]:
    ready_sources = [
        {"label": info.label, "root": str(info.root), "quarantine_dir": str(info.quarantine_dir), "ready": info.ready}
        for info in _sources.values()
        if info.ready
    ]
    issues = [
        {"label": info.label, "root": str(info.root), "issue": info.issue or "Netzlaufwerk nicht bereit"}
        for info in _sources.values()
        if not info.ready
    ]
    return {
        "file_ops_enabled": any(info.ready for info in _sources.values()),
        "quarantine_ready_sources": ready_sources,
        "quarantine_issues": issues,
        "quarantine_retention_days": _settings.retention_days,
        "quarantine_cleanup_schedule": _settings.cleanup_schedule,
        "quarantine_cleanup_dry_run": _settings.cleanup_dry_run,
        "quarantine_auto_purge_enabled": _settings.auto_purge_enabled,
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
    base_dir = _guard_path(info.root / safe_rel, info.root, allow_root=True, must_exist=True)
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
                    child_count: Optional[int] = None
                    try:
                        child_count_val = 0
                        with os.scandir(entry.path) as sub_it:
                            for sub in sub_it:
                                child_count_val += 1
                                if sub.is_dir():
                                    has_children = True
                        child_count = child_count_val
                    except Exception:
                        has_children = False
                        child_count = None
                    modified: Optional[float] = None
                    try:
                        modified = entry.stat(follow_symlinks=False).st_mtime
                    except Exception:
                        modified = None
                    entries.append(
                        {
                            "name": entry.name,
                            "path": rel_child,
                            "has_children": has_children,
                            "source": info.label,
                            "child_count": child_count,
                            "modified": modified,
                        }
                    )
                except Exception:
                    continue
    except FileNotFoundError:
        raise FileOpError("Pfad nicht gefunden", status_code=404)
    entries.sort(key=lambda e: e["name"].lower())
    return {"source": info.label, "path": safe_rel.as_posix(), "entries": entries}


def _resolve_source(label: str, fallback_root: Optional[str] = None) -> SourceInfo:
    info = _sources.get(label)
    if info:
        canonical_root = _canonical(info.root)
        quarantine_dir, ready, issue = ensure_quarantine(canonical_root, label)
        info = SourceInfo(label=label, root=canonical_root, quarantine_dir=quarantine_dir, ready=ready, issue=issue)
        _sources[label] = info
        if not ready:
            raise FileOpError(issue or "Netzlaufwerk nicht bereit", status_code=503)
        return info
    # Versuche, die Quelle aus aktiven Roots der DB zu laden
    try:
        for path, lab, _rid, active in config_db.list_roots(active_only=True):
            if lab == label and active:
                root_path = _canonical(Path(path))
                quarantine_dir, ready, issue = ensure_quarantine(root_path, lab)
                info = SourceInfo(label=lab, root=root_path, quarantine_dir=quarantine_dir, ready=ready, issue=issue)
                _sources[label] = info
                if not ready:
                    raise FileOpError(issue or "Netzlaufwerk nicht bereit", status_code=503)
                return info
    except FileOpError:
        raise
    except Exception:
        pass
    if not fallback_root:
        raise FileOpError("Quelle nicht verfügbar", status_code=400)
    root_path = _canonical(Path(fallback_root))
    quarantine_dir, ready, issue = ensure_quarantine(root_path, label)
    info = SourceInfo(label=label, root=root_path, quarantine_dir=quarantine_dir, ready=ready, issue=issue)
    _sources[label] = info
    if not ready:
        raise FileOpError(issue or "Netzlaufwerk nicht bereit", status_code=503)
    return info


def _assert_quarantine_ready(info: SourceInfo) -> None:
    if not info.ready:
        raise FileOpError(info.issue or "Netzlaufwerk nicht bereit", status_code=503)


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
    abs_path = _guard_path(abs_path, info.root, allow_root=False, must_exist=True)

    validated_name = _validate_new_filename(new_name, abs_path.name, abs_path.suffix)
    target_path = _guard_path(abs_path.parent / validated_name, info.root, allow_root=False, must_exist=False)
    if abs_path.parent != target_path.parent:
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


def move_file(doc_id: int, target_dir: str, target_source: Optional[str] = None, actor: str = "admin") -> Dict[str, object]:
    doc = resolve_doc(doc_id)
    if not doc:
        raise FileOpError("Dokument nicht gefunden", status_code=404)

    source_label = doc.get("source") or ""
    src_info = _resolve_source(source_label)
    _assert_quarantine_ready(src_info)
    dest_source_label = (target_source or source_label) or ""
    dest_info = _resolve_source(dest_source_label)
    _assert_quarantine_ready(dest_info)

    abs_path = doc.get("abs_path")
    if not isinstance(abs_path, Path):
        raise FileOpError("Pfad ungültig", status_code=400)
    abs_path = _guard_path(abs_path, src_info.root, allow_root=False, must_exist=True)

    safe_target_dir = _normalize_rel_path(target_dir)
    target_base = _guard_path(dest_info.root / safe_target_dir, dest_info.root, allow_root=True, must_exist=True)
    if not target_base.is_dir():
        raise FileOpError("Zielordner nicht gefunden", status_code=404)
    if str(target_base).startswith(str(dest_info.quarantine_dir)):
        raise FileOpError("Quarantäne kann nicht als Ziel genutzt werden", status_code=400)

    target_path = _guard_path(target_base / abs_path.name, dest_info.root, allow_root=False, must_exist=False)
    if target_path == abs_path and dest_source_label == source_label:
        raise FileOpError("Ziel entspricht dem aktuellen Ort", status_code=400)
    if target_path.exists():
        raise FileOpError("Ziel existiert bereits", status_code=409)

    audit_base = {
        "action": "move",
        "actor": actor or "admin",
        "doc_id": doc_id,
        "source": source_label,
        "dest_source": dest_source_label,
        "source_root": str(src_info.root),
        "dest_root": str(dest_info.root),
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
                    source=dest_source_label,
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


def copy_file(doc_id: int, target_dir: str, target_source: Optional[str] = None, actor: str = "admin") -> Dict[str, object]:
    doc = resolve_doc(doc_id)
    if not doc:
        raise FileOpError("Dokument nicht gefunden", status_code=404)

    source_label = doc.get("source") or ""
    src_info = _resolve_source(source_label)
    _assert_quarantine_ready(src_info)
    dest_source_label = (target_source or source_label) or ""
    dest_info = _resolve_source(dest_source_label)
    _assert_quarantine_ready(dest_info)

    abs_path = doc.get("abs_path")
    if not isinstance(abs_path, Path):
        raise FileOpError("Pfad ungültig", status_code=400)
    abs_path = _guard_path(abs_path, src_info.root, allow_root=False, must_exist=True)

    safe_target_dir = _normalize_rel_path(target_dir)
    target_base = _guard_path(dest_info.root / safe_target_dir, dest_info.root, allow_root=True, must_exist=True)
    if not target_base.is_dir():
        raise FileOpError("Zielordner nicht gefunden", status_code=404)
    if str(target_base).startswith(str(dest_info.quarantine_dir)):
        raise FileOpError("Quarantäne kann nicht als Ziel genutzt werden", status_code=400)

    target_path = _guard_path(target_base / abs_path.name, dest_info.root, allow_root=False, must_exist=False)
    if target_path.exists():
        raise FileOpError("Ziel existiert bereits", status_code=409)

    audit_base = {
        "action": "copy",
        "actor": actor or "admin",
        "doc_id": doc_id,
        "source": source_label,
        "dest_source": dest_source_label,
        "source_root": str(src_info.root),
        "dest_root": str(dest_info.root),
        "old_path": str(abs_path),
        "new_path": str(target_path),
    }

    content: Optional[str] = None
    title: Optional[str] = None
    try:
        with db.get_conn() as conn:
            content = db.get_document_content(conn, doc_id)
            title = db.get_document_title(conn, doc_id)
    except Exception:
        content = None
        title = None

    copied = False
    new_doc_id: Optional[int] = None
    with _locked_paths([target_path]):
        try:
            _copy_file_with_fsync(abs_path, target_path)
            try:
                shutil.copystat(abs_path, target_path, follow_symlinks=True)
            except Exception:
                pass
            copied = True
            stat_result = target_path.stat()
            meta = DocumentMeta(
                source=dest_source_label,
                path=str(target_path),
                filename=target_path.name,
                extension=target_path.suffix.lower(),
                size_bytes=stat_result.st_size,
                ctime=stat_result.st_ctime,
                mtime=stat_result.st_mtime,
                atime=getattr(stat_result, "st_atime", None),
                owner=doc.get("owner"),
                last_editor=doc.get("last_editor"),
                msg_from=doc.get("msg_from"),
                msg_to=doc.get("msg_to"),
                msg_cc=doc.get("msg_cc"),
                msg_subject=doc.get("msg_subject"),
                msg_date=doc.get("msg_date"),
                tags=doc.get("tags"),
                content=content or "",
                title_or_subject=title or target_path.name,
            )
            with db.get_conn() as conn:
                new_doc_id = db.upsert_document(conn, meta)
        except FileOpError as exc:
            if copied and target_path.exists():
                try:
                    target_path.unlink()
                except Exception:
                    pass
            _audit({**audit_base, "status": "error", "error": str(exc)})
            raise
        except Exception as exc:
            if copied and target_path.exists():
                try:
                    target_path.unlink()
                except Exception:
                    pass
            _audit({**audit_base, "status": "error", "error": str(exc)})
            raise

    _audit({**audit_base, "status": "ok", "new_doc_id": new_doc_id})
    return {
        "doc_id": doc_id,
        "new_doc_id": new_doc_id,
        "source": source_label,
        "dest_source": dest_source_label,
        "old_path": str(abs_path),
        "new_path": str(target_path),
        "display_name": target_path.name,
        "display_path": str(target_path),
    }


def create_upload_session(
    target_source: str,
    target_dir: str,
    files: List[Dict[str, object]],
    max_file_size_mb: Optional[int] = None,
) -> Dict[str, object]:
    if not files:
        raise FileOpError("Keine Dateien angegeben", status_code=400)
    info = _resolve_source(target_source)
    _assert_quarantine_ready(info)
    safe_target_dir = _normalize_rel_path(target_dir or "")
    target_base = _guard_path(info.root / safe_target_dir, info.root, allow_root=True, must_exist=True)
    if not target_base.is_dir():
        raise FileOpError("Zielordner nicht gefunden", status_code=404)
    if str(target_base).startswith(str(info.quarantine_dir)):
        raise FileOpError("Quarantäne kann nicht als Ziel genutzt werden", status_code=400)

    staging_root = info.quarantine_dir / "_uploads"
    try:
        staging_root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise FileOpError("Staging nicht beschreibbar", status_code=500) from exc
    session_id = uuid4().hex
    staging_dir = staging_root / session_id
    try:
        staging_dir.mkdir(parents=False, exist_ok=False)
    except Exception as exc:
        raise FileOpError("Staging nicht beschreibbar", status_code=500) from exc

    total_bytes = 0
    expected_names: set[str] = set()
    for entry in files:
        name = _sanitize_upload_name(str(entry.get("name", "")))
        size_val = int(entry.get("size") or 0)
        if size_val < 0:
            raise FileOpError("Ungültige Dateigröße", status_code=400)
        if max_file_size_mb and size_val > max_file_size_mb * 1024 * 1024:
            raise FileOpError("Datei zu groß", status_code=413)
        total_bytes += size_val
        expected_names.add(name)

    session = UploadSession(
        session_id=session_id,
        source_label=info.label,
        target_root=info.root,
        target_dir=safe_target_dir,
        quarantine_dir=info.quarantine_dir,
        staging_dir=staging_dir,
        total_files=len(files),
        total_bytes=total_bytes,
        overwrite_mode="reject",
        stage="uploading",
        expected_names=expected_names,
        index_status="idle",
    )
    _store_session(session)
    return {
        "session_id": session_id,
        "total_files": session.total_files,
        "total_bytes": session.total_bytes,
        "max_file_size_mb": max_file_size_mb,
        "target_source": info.label,
        "target_dir": safe_target_dir.as_posix(),
        "stage": session.stage,
    }


def save_upload_file(session_id: str, upload_file, name: Optional[str] = None, max_file_size_mb: Optional[int] = None) -> Dict[str, object]:
    session = _get_upload_session(session_id)
    if session.stage not in {"uploading", "init", "conflict"}:
        raise FileOpError("Upload bereits abgeschlossen", status_code=409)
    safe_name = _sanitize_upload_name(name or getattr(upload_file, "filename", ""))
    if session.expected_names and safe_name not in session.expected_names:
        raise FileOpError("Unerwarteter Dateiname", status_code=400)
    dest_path = session.staging_dir / safe_name
    if dest_path.exists():
        raise FileOpError("Datei bereits hochgeladen", status_code=409)
    size_limit_mb = max_file_size_mb or None
    written = 0
    try:
        with dest_path.open("wb") as fh:
            while True:
                chunk = upload_file.file.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                written += len(chunk)
                if size_limit_mb and written > size_limit_mb * 1024 * 1024:
                    raise FileOpError("Datei zu groß", status_code=413)
        if dest_path.is_symlink():
            dest_path.unlink(missing_ok=True)
            raise FileOpError("Symlinks nicht erlaubt", status_code=400)
    except FileOpError:
        try:
            dest_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    except Exception as exc:
        try:
            dest_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise FileOpError("Upload fehlgeschlagen", status_code=500) from exc

    session.uploaded_files += 1
    session.uploaded_bytes += written
    session.stage = "uploading"
    _store_session(session)
    return {"uploaded_files": session.uploaded_files, "total_files": session.total_files, "uploaded_bytes": session.uploaded_bytes}


def complete_upload_session(session_id: str, overwrite_mode: str = "reject") -> Dict[str, object]:
    session = _get_upload_session(session_id)
    session.overwrite_mode = overwrite_mode if overwrite_mode in {"rename", "reject", "overwrite"} else "reject"
    session.error = None
    session.conflicts = []
    if session.uploaded_files < session.total_files:
        raise FileOpError("Upload nicht vollständig", status_code=400)
    info = _resolve_source(session.source_label)
    _assert_quarantine_ready(info)
    safe_target_dir = _normalize_rel_path(session.target_dir.as_posix())
    target_base = _guard_path(info.root / safe_target_dir, info.root, allow_root=True, must_exist=True)
    if str(target_base).startswith(str(info.quarantine_dir)):
        raise FileOpError("Quarantäne kann nicht als Ziel genutzt werden", status_code=400)
    files = [p for p in session.staging_dir.iterdir() if p.is_file()]
    if not files:
        raise FileOpError("Keine Dateien hochgeladen", status_code=400)
    session.import_total = len(files)
    imported: List[Path] = []
    conflicts: List[str] = []
    for staged in files:
        target_candidate = _guard_path(target_base / staged.name, info.root, allow_root=False, must_exist=False)
        if target_candidate.exists() and session.overwrite_mode == "reject":
            conflicts.append(staged.name)
    if conflicts and session.overwrite_mode == "reject":
        session.stage = "conflict"
        session.conflicts = conflicts
        session.error = "Ziel existiert bereits"
        session.index_status = "idle"
        _store_session(session)
        raise FileOpError("Ziel existiert bereits", status_code=409)

    try:
        for staged in files:
            target_candidate = _guard_path(target_base / staged.name, info.root, allow_root=False, must_exist=False)
            if target_candidate.exists():
                if session.overwrite_mode == "rename":
                    target_candidate = _unique_target_path(target_candidate, info.root)
                elif session.overwrite_mode == "overwrite":
                    pass
                else:
                    raise FileOpError("Ziel existiert bereits", status_code=409)
            target_candidate.parent.mkdir(parents=True, exist_ok=True)
            with _locked_paths([target_candidate]):
                _move_file(staged, target_candidate)
            session.import_count += 1
            imported.append(target_candidate)
        session.stage = "imported"
        session.conflicts = []
        _store_session(session)
    except FileOpError as exc:
        session.stage = "error"
        session.error = str(exc)
        _store_session(session)
        raise
    except Exception as exc:
        session.stage = "error"
        session.error = "Import fehlgeschlagen"
        _store_session(session)
        raise FileOpError("Import fehlgeschlagen", status_code=500) from exc
    else:
        try:
            shutil.rmtree(session.staging_dir, ignore_errors=True)
        except Exception:
            pass
    return {
        "session_id": session.session_id,
        "import_count": session.import_count,
        "import_total": session.import_total,
        "imported": [str(p) for p in imported],
        "target_source": session.source_label,
        "target_root": str(info.root),
        "stage": session.stage,
    }


def abort_upload_session(session_id: str) -> None:
    session = _get_upload_session(session_id)
    try:
        shutil.rmtree(session.staging_dir, ignore_errors=True)
    except Exception:
        pass
    _remove_session(session_id)


def update_upload_index_status(session_id: str, status: str) -> None:
    try:
        session = _get_upload_session(session_id)
    except FileOpError:
        return
    session.index_status = status
    if status == "done" and session.stage != "error":
        session.stage = "done"
    elif status and status != "idle":
        session.stage = "indexing"
    _store_session(session)


def get_upload_status(session_id: str) -> Dict[str, object]:
    session = _get_upload_session(session_id)
    return {
        "session_id": session.session_id,
        "stage": session.stage,
        "error": session.error,
        "uploaded_files": session.uploaded_files,
        "total_files": session.total_files,
        "uploaded_bytes": session.uploaded_bytes,
        "total_bytes": session.total_bytes,
        "import_count": session.import_count,
        "import_total": session.import_total,
        "target_source": session.source_label,
        "target_dir": session.target_dir.as_posix(),
        "index_status": session.index_status,
        "conflicts": session.conflicts,
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
    abs_path = _guard_path(abs_path, info.root, allow_root=False, must_exist=True)

    date_folder = datetime.now().strftime("%Y-%m-%d")
    target_dir = info.quarantine_dir / date_folder
    target_path = target_dir / f"{doc_id}__{abs_path.name}"
    _guard_path(target_dir, info.quarantine_dir, allow_root=True, must_exist=False)
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


def _mark_missing_entry(entry: Dict[str, object], reason: str) -> None:
    try:
        with db.get_conn() as conn:
            db.mark_quarantine_cleanup_deleted(conn, entry["id"], datetime.now(timezone.utc).isoformat())
    except Exception:
        pass
    _audit(
        {
            "action": "quarantine_missing",
            "entry_id": entry.get("id"),
            "source": entry.get("source"),
            "quarantine_path": entry.get("quarantine_path"),
            "reason": reason,
            "status": "cleanup_marked",
        }
    )


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
        try:
            info = _resolve_source(entry.get("source") or "", fallback_root=entry.get("source_root"))
            quarantine_path = _guard_path(Path(entry.get("quarantine_path", "")), info.quarantine_dir, allow_root=False, must_exist=False)
            if not quarantine_path.exists():
                _mark_missing_entry(entry, "file_missing")
                continue
        except FileOpError:
            _mark_missing_entry(entry, "invalid_path")
            continue
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

    quarantine_path = _guard_path(Path(entry["quarantine_path"]), info.quarantine_dir, allow_root=False, must_exist=False)
    if not quarantine_path.exists():
        _mark_missing_entry(entry, "missing_on_restore")
        raise FileOpError("Datei in Quarantäne nicht gefunden", status_code=404)

    original_path = _guard_path(Path(entry["original_path"]), info.root, allow_root=False, must_exist=False)

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

    quarantine_path = _guard_path(Path(entry["quarantine_path"]), info.quarantine_dir, allow_root=False, must_exist=False)
    if not quarantine_path.exists():
        _mark_missing_entry(entry, "missing_on_hard_delete")
        return {"entry_id": entry_id, "deleted": False, "status": "missing"}

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
            safe_delete(quarantine_path, info.quarantine_dir)
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
        try:
            _assert_safe_root(info.root)
        except FileOpError:
            summary["errors"] += 1
            continue
        base = info.quarantine_dir
        try:
            base = _guard_path(base, info.root, allow_root=False, must_exist=False)
        except FileOpError:
            summary["errors"] += 1
            continue
        if not base.exists():
            try:
                base.mkdir(parents=True, exist_ok=True)
            except Exception:
                continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.name.startswith(".rw_test"):
                continue
            try:
                _guard_path(path, base, allow_root=False, must_exist=True)
            except FileOpError:
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
                # Kann auftreten, wenn temporäre Backups (z. B. .rename_backup) bereits entfernt wurden.
                continue
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
                    try:
                        safe_delete(path, base)
                    except FileOpError as exc:
                        if getattr(exc, "status_code", None) == 404:
                            continue
                        _audit({**audit_base, "status": "error", "error": str(exc)})
                        summary["errors"] += 1
                        continue
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
    if not _settings.auto_purge_enabled:
        return
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
                logger.warning("Quarantäne-Cleanup Warnung: %s", exc)
            _cleanup_stop.wait(interval)

    _cleanup_thread = threading.Thread(target=worker, daemon=True)
    _cleanup_thread.start()


def stop_cleanup_scheduler() -> None:
    _cleanup_stop.set()
    if _cleanup_thread and _cleanup_thread.is_alive():
        _cleanup_thread.join(timeout=2)
