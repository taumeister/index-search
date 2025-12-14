import configparser
import dataclasses
from dataclasses import field
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, field_validator

from app import config_db


class PathsConfig(BaseModel):
    roots: list[tuple[Path, str]] = []

    @classmethod
    def from_raw(cls, value: str) -> "PathsConfig":
        roots: list[tuple[Path, str]] = []
        for item in (value or "").split(","):
            raw = item.strip()
            if not raw:
                continue
            if ":" in raw:
                path_s, label = raw.split(":", 1)
                roots.append((Path(path_s.strip()), label.strip() or Path(path_s.strip()).name))
            else:
                roots.append((Path(raw), Path(raw).name))
        return cls(roots=roots)


class IndexerConfig(BaseModel):
    worker_count: int = 2
    run_interval_cron: Optional[str] = None
    max_file_size_mb: Optional[int] = None

    @field_validator("worker_count")
    def validate_worker(cls, value: int) -> int:
        if value < 1:
            raise ValueError("worker_count muss >=1 sein")
        return value

    @field_validator("max_file_size_mb")
    def validate_size(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 0:
            raise ValueError("max_file_size_mb darf nicht negativ sein")
        return value


class SMTPConfig(BaseModel):
    host: str
    port: int
    use_tls: bool
    username: Optional[str]
    password: Optional[str]
    sender: str
    recipients: list[str]


class UIConfig(BaseModel):
    default_preview: str = "panel"
    snippet_length: int = 160
    search_default_mode: str = "standard"
    search_prefix_minlen: int = 4

    @field_validator("search_default_mode")
    def validate_mode(cls, value: str) -> str:
        value = (value or "standard").strip().lower()
        if value not in {"strict", "standard", "loose"}:
            raise ValueError("search_default_mode muss strict|standard|loose sein")
        return value

    @field_validator("search_prefix_minlen")
    def validate_prefix_minlen(cls, value: int) -> int:
        if value is None or value < 1:
            raise ValueError("search_prefix_minlen muss >=1 sein")
        return value


class LoggingConfig(BaseModel):
    level: str = "INFO"
    log_dir: Path = Path("logs")
    rotation_mb: int = 10

    @field_validator("rotation_mb")
    def validate_rotation(cls, value: int) -> int:
        if value < 1:
            raise ValueError("rotation_mb muss positiv sein")
        return value


class FeedbackConfig(BaseModel):
    enabled: bool = False
    recipients: list[str] = []


@dataclasses.dataclass
class CentralConfig:
    paths: PathsConfig
    indexer: IndexerConfig
    smtp: Optional[SMTPConfig]
    ui: UIConfig
    logging: LoggingConfig
    report_enabled: bool = False
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
    raw: Optional[configparser.ConfigParser] = None


def load_config(path: Path = Path("config/central_config.ini"), use_env: bool = True) -> CentralConfig:
    """
    ENV-getriebene Konfiguration für Docker-Betrieb.
    """
    env_roots = os.getenv("INDEX_ROOTS", "") if use_env else ""
    roots_list: list[tuple[Path, str]] = []
    if env_roots:
        for item in env_roots.split(","):
            raw = item.strip()
            if not raw:
                continue
            if ":" in raw:
                path_s, label = raw.split(":", 1)
                roots_list.append((Path(path_s.strip()), label.strip() or Path(path_s.strip()).name))
            else:
                roots_list.append((Path(raw), Path(raw).name))
    paths_cfg = PathsConfig(roots=roots_list)

    worker_raw = int(os.getenv("INDEX_WORKER_COUNT", "2") or 2) if use_env else 2
    if worker_raw < 1:
        raise ValueError("INDEX_WORKER_COUNT muss >=1 sein")
    max_size_raw = int(os.getenv("INDEX_MAX_FILE_SIZE_MB", "0") or 0) if use_env else 0
    indexer_cfg = IndexerConfig(
        worker_count=worker_raw,
        run_interval_cron=None,
        max_file_size_mb=max_size_raw or None,
    )

    smtp_host = os.getenv("SMTP_HOST", "") if use_env else ""
    smtp_cfg: Optional[SMTPConfig] = None
    if smtp_host:
        smtp_cfg = SMTPConfig(
            host=smtp_host,
            port=int(os.getenv("SMTP_PORT", "587")),
            use_tls=os.getenv("SMTP_USE_TLS", "true").lower() == "true",
            username=os.getenv("SMTP_USER", "") or None,
            password=os.getenv("SMTP_PASS", "") or None,
            sender=os.getenv("SMTP_FROM", "index-search@localhost"),
            recipients=[r.strip() for r in os.getenv("SMTP_TO", "").split(",") if r.strip()],
        )

    ui_cfg = UIConfig(
        default_preview="panel",
        snippet_length=160,
        search_default_mode=os.getenv("SEARCH_DEFAULT_MODE", "standard") if use_env else "standard",
        search_prefix_minlen=int(os.getenv("SEARCH_PREFIX_MINLEN", "4") or 4) if use_env else 4,
    )
    logging_cfg = LoggingConfig(
        level=os.getenv("LOG_LEVEL", "INFO") if use_env else "INFO",
        log_dir=Path(os.getenv("LOG_DIR", "logs")) if use_env else Path("logs"),
        rotation_mb=int(os.getenv("LOG_ROTATION_MB", "10")) if use_env else 10,
    )

    feedback_cfg = FeedbackConfig(
        enabled=os.getenv("FEEDBACK_ENABLED", "false").lower() == "true" if use_env else False,
        recipients=[r.strip() for r in (os.getenv("FEEDBACK_TO", "") if use_env else "").split(",") if r.strip()],
    )

    return CentralConfig(
        paths=paths_cfg,
        indexer=indexer_cfg,
        smtp=smtp_cfg,
        ui=ui_cfg,
        logging=logging_cfg,
        report_enabled=False,  # Dashboard steuert das Flag
        feedback=feedback_cfg,
        raw=None,
    )


def ensure_dirs(config: CentralConfig) -> None:
    config.logging.log_dir.mkdir(parents=True, exist_ok=True)
    Path("data").mkdir(exist_ok=True)
