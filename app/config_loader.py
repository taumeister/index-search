import configparser
import dataclasses
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, EmailStr, ValidationError, field_validator
from app import config_db


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
    raw: Optional[configparser.ConfigParser]


def _read_ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    if not path.exists():
        return parser
    parser.read(path)
    return parser


def load_config(path: Path = Path("config/central_config.ini")) -> CentralConfig:
    """
    Load configuration from SQLite config DB (default path) or from an INI file.
    Non-default paths always bypass the config DB to allow isolated configs (e.g. tests).
    """
    use_config_db = path == Path("config/central_config.ini") and os.getenv("DISABLE_CONFIG_DB") != "1"

    if not use_config_db:
        parser = _read_ini(path)
        paths_raw = parser.get("paths", "roots", fallback="").strip()
        paths_cfg = PathsConfig.from_raw(paths_raw)
        indexer_cfg = IndexerConfig(
            worker_count=parser.getint("indexer", "worker_count", fallback=2),
            run_interval_cron=parser.get("indexer", "run_interval_cron", fallback=None),
            max_file_size_mb=parser.getint("indexer", "max_file_size_mb", fallback=None),
        )
        smtp_cfg = None
    ui_cfg = UIConfig(
        default_preview=parser.get("ui", "default_preview", fallback="panel"),
        snippet_length=parser.getint("ui", "snippet_length", fallback=160),
    )
        logging_cfg = LoggingConfig(
            level=parser.get("logging", "level", fallback="INFO"),
            log_dir=Path(parser.get("logging", "log_dir", fallback="logs")),
            rotation_mb=parser.getint("logging", "rotation_mb", fallback=10),
        )
        return CentralConfig(
            paths=paths_cfg,
            indexer=indexer_cfg,
            smtp=smtp_cfg,
            ui=ui_cfg,
            logging=logging_cfg,
            raw=parser,
        )

    config_db.ensure_db()

    roots_list = [(Path(p), label) for p, label, _id, _active in config_db.list_roots(active_only=True)]
    paths_cfg = PathsConfig(roots=roots_list)

    def setting(key: str, default: str) -> str:
        val = config_db.get_setting(key, None)
        return val if val is not None else default

    indexer_cfg = IndexerConfig(
        worker_count=int(setting("worker_count", "2") or 2),
        run_interval_cron=None,
        max_file_size_mb=int(setting("max_file_size_mb", "") or 0) or None,
    )

    smtp_cfg: Optional[SMTPConfig] = None

    ui_cfg = UIConfig(
        default_preview=setting("default_preview", "panel") or "panel",
        snippet_length=int(setting("snippet_length", "160") or 160),
    )
    logging_cfg = LoggingConfig(
        level=setting("logging_level", "INFO") or "INFO",
        log_dir=Path(setting("log_dir", "logs") or "logs"),
        rotation_mb=int(setting("rotation_mb", "10") or 10),
    )

    return CentralConfig(
        paths=paths_cfg,
        indexer=indexer_cfg,
        smtp=smtp_cfg,
        ui=ui_cfg,
        logging=logging_cfg,
        raw=None,
    )


def ensure_dirs(config: CentralConfig) -> None:
    config.logging.log_dir.mkdir(parents=True, exist_ok=True)
    Path("data").mkdir(exist_ok=True)
