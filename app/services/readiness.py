import errno
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass
class ReadinessIssue:
    source: str
    path: str
    reason: str
    errno: Optional[int] = None


@dataclass
class ReadinessResult:
    ok: bool
    issues: List[ReadinessIssue]

    @property
    def message(self) -> Optional[str]:
        if self.ok or not self.issues:
            return None
        first = self.issues[0]
        return f"Netzlaufwerk nicht bereit: {first.reason} ({first.path})"


def _canonical(path: Path) -> Path:
    try:
        return path.resolve()
    except Exception:
        return Path(os.path.abspath(path))


def _listdir_probe(path: Path) -> Tuple[bool, Optional[int], Optional[bool], List[os.DirEntry]]:
    """
    Returns (ok, errno, is_empty, sample_entries)
    errno is set if an OSError occurred.
    """
    entries: List[os.DirEntry] = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                entries.append(entry)
                if len(entries) >= 5:
                    break
        return True, None, len(entries) == 0, entries
    except OSError as exc:
        return False, exc.errno, None, []


def check_sources_ready(
    sources: Iterable[Tuple[Path, str]],
    existing_counts: Optional[Dict[str, int]] = None,
    sample_paths: Optional[Dict[str, str]] = None,
    require_non_empty: bool = False,
) -> ReadinessResult:
    issues: List[ReadinessIssue] = []
    counts = existing_counts or {}
    samples = sample_paths or {}
    for raw_root, label in sources:
        canonical = _canonical(raw_root)
        label_safe = label or canonical.name
        if str(canonical) in {"", "/"}:
            issues.append(ReadinessIssue(source=label_safe, path=str(canonical), reason="Ungültiger Wurzelpfad"))
            continue
        if not canonical.exists() or not canonical.is_dir():
            issues.append(ReadinessIssue(source=label_safe, path=str(canonical), reason="Pfad nicht gefunden"))
            continue
        if not os.access(canonical, os.R_OK | os.X_OK):
            issues.append(ReadinessIssue(source=label_safe, path=str(canonical), reason="Kein Lesezugriff", errno=None))
            continue
        try:
            canonical.stat()
        except OSError as exc:
            issues.append(ReadinessIssue(source=label_safe, path=str(canonical), reason="Stat fehlgeschlagen", errno=exc.errno))
            continue
        ok, errno_val, is_empty, entries = _listdir_probe(canonical)
        if not ok:
            issues.append(ReadinessIssue(source=label_safe, path=str(canonical), reason="Lesen fehlgeschlagen", errno=errno_val))
            continue
        if (is_empty and counts.get(label_safe, 0) > 0) or (is_empty and require_non_empty):
            issues.append(
                ReadinessIssue(
                    source=label_safe,
                    path=str(canonical),
                    reason="Quelle liefert keine Dateien (evtl. offline?)",
                    errno=None,
                )
            )
            continue
        sample_attempts = 0
        sample_success = False
        errno_val: Optional[int] = None
        files: List[os.DirEntry] = []
        dirs: List[os.DirEntry] = []
        for entry in entries:
            if entry.is_symlink():
                continue
            try:
                if entry.is_file(follow_symlinks=False):
                    files.append(entry)
                else:
                    dirs.append(entry)
            except OSError as exc:
                errno_val = exc.errno
                continue

        for entry in files:
            sample_attempts += 1
            try:
                entry_path = Path(entry.path)
                entry_path.open("rb").read(1)
                sample_success = True
                break
            except OSError as exc:
                errno_val = exc.errno
                continue

        if not sample_success:
            for entry in dirs:
                sample_attempts += 1
                try:
                    with os.scandir(entry.path) as sub_it:
                        next(sub_it, None)
                    sample_success = True
                    break
                except OSError as exc:
                    errno_val = exc.errno
                    continue

        if sample_attempts > 0 and not sample_success:
            issues.append(
                ReadinessIssue(
                    source=label_safe,
                    path=str(canonical),
                    reason="Dateizugriff fehlgeschlagen (Netzlaufwerk nicht bereit?)",
                    errno=errno_val,
                )
            )
            continue

        sample_path = samples.get(label_safe)
        if sample_path:
            try:
                probe = Path(sample_path)
                if not probe.exists():
                    raise OSError(errno.ENOENT)
                with probe.open("rb") as fh:
                    fh.read(1)
            except Exception as exc:
                err_no = getattr(exc, "errno", None)
                issues.append(
                    ReadinessIssue(
                        source=label_safe,
                        path=str(sample_path),
                        reason="Probe-Datei nicht lesbar",
                        errno=err_no,
                    )
                )
    return ReadinessResult(ok=not issues, issues=issues)


def check_quarantine_writable(quarantine_path: Path) -> ReadinessResult:
    path = _canonical(quarantine_path)
    issues: List[ReadinessIssue] = []
    if str(path) in {"", "/"}:
        issues.append(ReadinessIssue(source="", path=str(path), reason="Ungültiger Quarantäne-Pfad"))
        return ReadinessResult(ok=False, issues=issues)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        issues.append(ReadinessIssue(source="", path=str(path), reason="Quarantäne kann nicht angelegt werden", errno=exc.errno))
        return ReadinessResult(ok=False, issues=issues)

    tmp_file = None
    try:
        fd, tmp_file = tempfile.mkstemp(prefix=".rw_test_", suffix=".tmp", dir=path)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("ok")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        issues.append(ReadinessIssue(source="", path=str(path), reason="Quarantäne nicht beschreibbar", errno=exc.errno))
    finally:
        if tmp_file:
            try:
                os.unlink(tmp_file)
            except Exception:
                pass
    return ReadinessResult(ok=not issues, issues=issues)
