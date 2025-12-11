import configparser
import dataclasses
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, EmailStr, ValidationError, field_validator


class PathsConfig(BaseModel):
    roots: List[Tuple[Path, str]] = []

    @classmethod
    def from_raw(cls, raw: str) -> "PathsConfig":
        """
        Accepts a comma separated list of paths or path:label pairs.
        If no label is provided the last directory name is used.
        """
        if not raw.strip():
            return cls(roots=[])
        entries: List[Tuple[Path, str]] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                path_str, label = part.split(":", 1)
                label = label.strip() or Path(path_str).name
            else:
                path_str, label = part, Path(part).name
            path = Path(path_str).expanduser()
            entries.append((path, label))
        return cls(roots=entries)

    @field_validator("roots")
    def validate_roots(cls, roots: List[Tuple[Path, str]]) -> List[Tuple[Path, str]]:
        validated: List[Tuple[Path, str]] = []
        seen_labels: set[str] = set()
        for path, label in roots:
            if not label:
                raise ValueError(f"Leeres source-Label für Pfad {path}")
            if label in seen_labels:
                raise ValueError(f"Doppeltes source-Label: {label}")
            seen_labels.add(label)
            validated.append((path, label))
        return validated


class IndexerConfig(BaseModel):
    worker_count: int = 2
    run_interval_cron: Optional[str] = None
    max_file_size_mb: Optional[int] = None

    @field_validator("worker_count")
    def validate_workers(cls, value: int) -> int:
        if value < 1 or value > 8:
            raise ValueError("worker_count muss zwischen 1 und 8 liegen")
        return value

    @field_validator("max_file_size_mb")
    def validate_max_size(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 1:
            raise ValueError("max_file_size_mb muss positiv sein")
        return value


class SMTPConfig(BaseModel):
    host: str
    port: int
    use_tls: bool = True
    username: Optional[str] = None
    password: Optional[str] = None
    sender: EmailStr
    recipients: List[EmailStr]

    @field_validator("port")
    def validate_port(cls, value: int) -> int:
        if value <= 0 or value > 65535:
            raise ValueError("port muss zwischen 1 und 65535 liegen")
        return value

    @field_validator("recipients")
    def validate_recipients(cls, value: List[EmailStr]) -> List[EmailStr]:
        if not value:
            raise ValueError("mindestens ein Empfänger erforderlich")
        return value


class UIConfig(BaseModel):
    default_preview: str = "panel"
    snippet_length: int = 240

    @field_validator("default_preview")
    def validate_preview(cls, value: str) -> str:
        allowed = {"panel", "popup"}
        if value not in allowed:
            raise ValueError(f"default_preview muss in {allowed} liegen")
        return value

    @field_validator("snippet_length")
    def validate_snippet(cls, value: int) -> int:
        if value < 40 or value > 800:
            raise ValueError("snippet_length muss zwischen 40 und 800 liegen")
        return value


class LoggingConfig(BaseModel):
    level: str = "INFO"
    log_dir: Path = Path("logs")
    rotation_mb: int = 10

    @field_validator("level")
    def validate_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR"}
        if value.upper() not in allowed:
            raise ValueError(f"log level muss in {allowed} liegen")
        return value.upper()

    @field_validator("rotation_mb")
    def validate_rotation(cls, value: int) -> int:
        if value < 1:
            raise ValueError("rotation_mb muss positiv sein")
        return value


@dataclasses.dataclass
class CentralConfig:
    paths: PathsConfig
    indexer: IndexerConfig
    smtp: Optional[SMTPConfig]
    ui: UIConfig
    logging: LoggingConfig
    raw: configparser.ConfigParser


def _read_ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    if not path.exists():
        return parser
    parser.read(path)
    return parser


def load_config(path: Path = Path("config/central_config.ini")) -> CentralConfig:
    parser = _read_ini(path)

    def get(section: str, option: str, fallback: Optional[str] = None) -> str:
        return parser.get(section, option, fallback=fallback) if parser.has_option(section, option) else (fallback or "")

    paths_cfg = PathsConfig.from_raw(get("paths", "roots", ""))
    indexer_cfg = IndexerConfig(
        worker_count=int(get("indexer", "worker_count", "2") or 2),
        run_interval_cron=get("indexer", "run_interval_cron", None) or None,
        max_file_size_mb=int(get("indexer", "max_file_size_mb", "0") or 0) or None,
    )

    smtp_cfg: Optional[SMTPConfig] = None
    if parser.has_section("smtp"):
        smtp_enabled = get("smtp", "host")
        if smtp_enabled:
            recipients_raw = get("smtp", "to", "")
            recipients = [email.strip() for email in recipients_raw.split(",") if email.strip()]
            smtp_cfg = SMTPConfig(
                host=smtp_enabled,
                port=int(get("smtp", "port", "587")),
                use_tls=get("smtp", "use_tls", "true").lower() in {"1", "true", "yes", "on"},
                username=get("smtp", "username", None) or None,
                password=get("smtp", "password", None) or None,
                sender=get("smtp", "from", ""),
                recipients=recipients,
            )

    ui_cfg = UIConfig(
        default_preview=get("ui", "default_preview", "panel") or "panel",
        snippet_length=int(get("ui", "snippet_length", "240") or 240),
    )
    logging_cfg = LoggingConfig(
        level=get("logging", "level", "INFO") or "INFO",
        log_dir=Path(get("logging", "log_dir", "logs") or "logs"),
        rotation_mb=int(get("logging", "rotation_mb", "10") or 10),
    )

    return CentralConfig(
        paths=paths_cfg,
        indexer=indexer_cfg,
        smtp=smtp_cfg,
        ui=ui_cfg,
        logging=logging_cfg,
        raw=parser,
    )


def ensure_dirs(config: CentralConfig) -> None:
    config.logging.log_dir.mkdir(parents=True, exist_ok=True)
    Path("data").mkdir(exist_ok=True)
