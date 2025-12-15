import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Iterable, Callable, Dict, Any

from app import config_db

logger = logging.getLogger(__name__)


@dataclass
class AutoIndexConfig:
    enabled: bool = False
    mode: str = "daily"  # daily | weekly | interval
    time: str = "02:00"  # HH:MM
    weekday: int = 0  # 0=Montag
    interval_hours: int = 6


@dataclass
class AutoIndexStatus:
    last_run_at: Optional[datetime] = None
    last_duration_sec: Optional[float] = None
    last_status: str = "idle"
    last_error: Optional[str] = None
    next_run_at: Optional[datetime] = None
    running: bool = False


def parse_time_str(value: str) -> tuple[int, int]:
    try:
        hh, mm = value.split(":")
        return int(hh), int(mm)
    except Exception:
        return 2, 0


def compute_next_run(cfg: AutoIndexConfig, now: Optional[datetime] = None) -> Optional[datetime]:
    if not cfg.enabled:
        return None
    now = now or datetime.now(timezone.utc)
    if cfg.mode == "interval":
        hours = max(1, int(cfg.interval_hours or 6))
        return now + timedelta(hours=hours)
    hh, mm = parse_time_str(cfg.time)
    local_now = now.astimezone()
    target = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if cfg.mode == "daily":
        if target <= local_now:
            target += timedelta(days=1)
    elif cfg.mode == "weekly":
        weekday = max(0, min(6, int(cfg.weekday or 0)))
        days_ahead = (weekday - target.weekday()) % 7
        if days_ahead == 0 and target <= local_now:
            days_ahead = 7
        target += timedelta(days=days_ahead)
    else:
        return None
    return target.astimezone(timezone.utc)


def load_config_from_db() -> AutoIndexConfig:
    raw = config_db.get_auto_index_config()
    return AutoIndexConfig(
        enabled=str(raw.get("auto_index_enabled") or "0").lower() == "1",
        mode=(raw.get("auto_index_mode") or "daily").strip().lower(),
        time=raw.get("auto_index_time") or "02:00",
        weekday=int(raw.get("auto_index_weekday") or 0),
        interval_hours=int(raw.get("auto_index_interval_hours") or 6),
    )


def persist_config(cfg: AutoIndexConfig) -> None:
    config_db.set_auto_index_config(
        {
            "auto_index_enabled": "1" if cfg.enabled else "0",
            "auto_index_mode": cfg.mode,
            "auto_index_time": cfg.time,
            "auto_index_weekday": str(cfg.weekday),
            "auto_index_interval_hours": str(cfg.interval_hours),
        }
    )


def load_status_from_db() -> AutoIndexStatus:
    raw = config_db.get_auto_index_status()
    def parse_dt(val: Optional[str]) -> Optional[datetime]:
        if not val:
            return None
        try:
            return datetime.fromisoformat(val)
        except Exception:
            return None
    return AutoIndexStatus(
        last_run_at=parse_dt(raw.get("auto_index_last_run_at")),
        last_duration_sec=float(raw.get("auto_index_last_duration") or 0) or None,
        last_status=raw.get("auto_index_last_status") or "idle",
        last_error=raw.get("auto_index_last_error") or None,
        next_run_at=parse_dt(raw.get("auto_index_next_run_at")),
        running=False,
    )


def persist_status(status: AutoIndexStatus) -> None:
    def fmt_dt(dt: Optional[datetime]) -> str:
        return dt.astimezone(timezone.utc).isoformat() if dt else ""
    payload = {
        "auto_index_last_run_at": fmt_dt(status.last_run_at),
        "auto_index_last_duration": str(status.last_duration_sec or ""),
        "auto_index_last_status": status.last_status or "",
        "auto_index_last_error": status.last_error or "",
        "auto_index_next_run_at": fmt_dt(status.next_run_at),
    }
    config_db.set_auto_index_status(payload)


class AutoIndexScheduler:
    def __init__(self, start_handler: Callable[..., str]):
        self._start_handler = start_handler
        self._stop_event = threading.Event()
        self._poke_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Auto-Index-Scheduler gestartet")

    def stop(self):
        self._stop_event.set()
        self._poke_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("Auto-Index-Scheduler gestoppt")

    def update_config(self, cfg: AutoIndexConfig):
        persist_config(cfg)
        self._poke_event.set()

    def status(self) -> AutoIndexStatus:
        status = load_status_from_db()
        status.running = self._running
        return status

    def trigger_now(self) -> str:
        return self._launch_run(reason="manual")

    def _run_loop(self):
        while not self._stop_event.is_set():
            cfg = load_config_from_db()
            if not cfg.enabled:
                status = self.status()
                status.next_run_at = None
                persist_status(status)
                self._wait_for(30)
                continue
            next_run = compute_next_run(cfg)
            status = self.status()
            status.next_run_at = next_run
            persist_status(status)
            if not next_run:
                self._wait_for(60)
                continue
            now = datetime.now(timezone.utc)
            wait_sec = max(1, (next_run - now).total_seconds())
            if self._wait_for(wait_sec):
                continue
            # fällig
            result = self._launch_run(reason="auto")
            if result == "busy":
                logger.info("Auto-Index übersprungen: Lauf läuft bereits")
                # Rechne nächsten Termin ab jetzt
                next_after_busy = compute_next_run(cfg, datetime.now(timezone.utc))
                status = self.status()
                status.next_run_at = next_after_busy
                persist_status(status)

    def _wait_for(self, seconds: float) -> bool:
        # returns True if woken by poke/stop
        self._poke_event.clear()
        woke = self._poke_event.wait(timeout=seconds) or self._stop_event.is_set()
        return woke

    def _launch_run(self, reason: str) -> str:
        if self._running:
            return "busy"
        status = self.status()
        now = datetime.now(timezone.utc)
        status.last_status = "running"
        status.last_run_at = now
        status.last_error = None
        status.running = True
        persist_status(status)
        self._running = True

        def on_finish(res_status: str, started_at: datetime, finished_at: datetime, err: Optional[str]):
            duration = (finished_at - started_at).total_seconds()
            st = self.status()
            st.running = False
            st.last_status = res_status
            st.last_run_at = started_at
            st.last_duration_sec = duration
            st.last_error = err
            st.next_run_at = compute_next_run(load_config_from_db(), finished_at)
            persist_status(st)
            self._running = False
            self._poke_event.set()

        result = self._start_handler(full_reset=False, reason=reason, on_finish=on_finish)
        if result == "busy":
            self._running = False
            status = self.status()
            status.last_status = "busy"
            status.running = False
            persist_status(status)
        return result
