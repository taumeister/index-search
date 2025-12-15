import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config_db
from app.auto_index_scheduler import AutoIndexConfig, compute_next_run
from app.index_runner import index_lock, start_index_run
from app.main import create_app


def setup_env(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    os.environ["APP_SECRET"] = "secret"
    os.environ["AUTO_INDEX_DISABLE"] = "1"
    for key in [
        "INDEX_ROOTS",
        "INDEX_WORKER_COUNT",
        "INDEX_MAX_FILE_SIZE_MB",
        "SEARCH_DEFAULT_MODE",
        "SEARCH_PREFIX_MINLEN",
        "FEEDBACK_ENABLED",
        "FEEDBACK_TO",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USE_TLS",
        "SMTP_USER",
        "SMTP_PASS",
        "SMTP_FROM",
        "SMTP_TO",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_compute_next_run_daily_future():
    cfg = AutoIndexConfig(enabled=True, mode="daily", time="10:00")
    now = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    nxt = compute_next_run(cfg, now)
    assert nxt is not None
    assert nxt.astimezone().hour == 10


def test_compute_next_run_daily_next_day():
    cfg = AutoIndexConfig(enabled=True, mode="daily", time="07:00")
    now = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    nxt = compute_next_run(cfg, now)
    assert nxt.date() == (now + timedelta(days=1)).date()


def test_compute_next_run_weekly():
    cfg = AutoIndexConfig(enabled=True, mode="weekly", time="06:30", weekday=2)
    now = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)  # Montag
    nxt = compute_next_run(cfg, now)
    assert nxt.weekday() == 2  # Mittwoch


def test_compute_next_run_interval():
    cfg = AutoIndexConfig(enabled=True, mode="interval", interval_hours=6)
    now = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    nxt = compute_next_run(cfg, now)
    assert nxt - now == timedelta(hours=6)


def test_start_index_run_busy(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)

    def dummy_run(*args, **kwargs):
        pass

    monkeypatch.setattr("app.index_runner.run_index_lauf", dummy_run)
    index_lock.acquire()
    try:
        res = start_index_run(resolve_roots=lambda cfg: [(tmp_path, "root")])
        assert res == "busy"
    finally:
        index_lock.release()


def test_auto_index_config_endpoints(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    monkeypatch.setattr("app.db.datenbank.DB_PATH", tmp_path / "index.db")
    app = create_app()
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}

    resp = client.get("/api/auto-index/config", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "config" in data

    payload = {
        "enabled": True,
        "mode": "daily",
        "time": "03:30",
        "weekday": 1,
        "interval_hours": 12,
    }
    resp = client.post("/api/auto-index/config", json=payload, headers=headers)
    assert resp.status_code == 200
    cfg = resp.json()["config"]
    assert cfg["enabled"] is True
    assert cfg["time"] == "03:30"

    resp = client.post("/api/auto-index/run", headers=headers)
    # Scheduler deaktiviert, Start kann busy sein falls Lock gesetzt, sonst started
    assert resp.status_code in {200, 409}
