import errno
import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.db import datenbank as db


@dataclass
class SourceInfo:
    label: str
    root: Path
    quarantine_dir: Path
    ready: bool


class FileOpError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


AUDIT_LOG = Path("data/audit/file_ops.jsonl")
_sources: Dict[str, SourceInfo] = {}


def _canonical(path: Path) -> Path:
    try:
        return path.resolve()
    except Exception:
        return Path(os.path.abspath(path))


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


def get_status() -> Dict[str, object]:
    ready_sources = [
        {"label": info.label, "root": str(info.root), "quarantine_dir": str(info.quarantine_dir), "ready": info.ready}
        for info in _sources.values()
        if info.ready
    ]
    return {
        "file_ops_enabled": any(info.ready for info in _sources.values()),
        "quarantine_ready_sources": ready_sources,
    }


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


def check_within_root(path: Path, root: Path) -> bool:
    try:
        canonical_path = _canonical(path)
        canonical_root = _canonical(root)
        return canonical_path.is_relative_to(canonical_root)
    except Exception:
        return False


def _copy_file_with_fsync(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as fsrc, dest.open("wb") as fdst:
        shutil.copyfileobj(fsrc, fdst, length=1024 * 1024)
        fdst.flush()
        os.fsync(fdst.fileno())


def _move_to_quarantine(src: Path, dest: Path) -> None:
    try:
        os.replace(src, dest)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    _copy_file_with_fsync(src, dest)
    os.unlink(src)


def _audit(entry: Dict[str, object]) -> None:
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def quarantine_delete(doc_id: int, actor: str = "admin") -> Dict[str, object]:
    doc = resolve_doc(doc_id)
    if not doc:
        raise FileOpError("Dokument nicht gefunden", status_code=404)

    source_label = doc.get("source") or ""
    info = _sources.get(source_label)
    if not info:
        raise FileOpError("Quelle nicht verfügbar", status_code=400)

    quarantine_dir, ready = ensure_quarantine(info.root)
    info = SourceInfo(label=info.label, root=info.root, quarantine_dir=quarantine_dir, ready=ready)
    _sources[source_label] = info
    if not info.ready:
        raise FileOpError("Quarantäne nicht verfügbar", status_code=400)

    abs_path = doc.get("abs_path")
    if not isinstance(abs_path, Path):
        raise FileOpError("Pfad ungültig", status_code=400)
    if not check_within_root(abs_path, info.root):
        raise FileOpError("Pfad liegt außerhalb der Quelle", status_code=400)
    if not abs_path.exists():
        raise FileOpError("Datei nicht gefunden", status_code=404)

    date_folder = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target_dir = info.quarantine_dir / date_folder
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{doc_id}__{abs_path.name}"

    audit_base = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": actor or "admin",
        "doc_id": doc_id,
        "source": source_label,
        "source_root": str(info.root),
        "original_path": str(abs_path),
        "quarantine_path": str(target_path),
    }
    try:
        _move_to_quarantine(abs_path, target_path)
        with db.get_conn() as conn:
            db.remove_document_by_id(conn, doc_id)
        audit_entry = {**audit_base, "status": "ok"}
        _audit(audit_entry)
        return {
            "doc_id": doc_id,
            "source": source_label,
            "original_path": str(abs_path),
            "quarantine_path": str(target_path),
            "removed_from_index": True,
        }
    except FileOpError:
        audit_entry = {**audit_base, "status": "error", "error": "validation"}
        _audit(audit_entry)
        raise
    except Exception as exc:
        audit_entry = {**audit_base, "status": "error", "error": str(exc)}
        _audit(audit_entry)
        raise
