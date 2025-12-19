import os
from pathlib import Path

from fastapi.testclient import TestClient

from app import config_db, metrics_db
from app.config_loader import load_config
from app.db import datenbank as db
from app.main import create_app


def build_test_client(tmp_path: Path, monkeypatch) -> TestClient:
    os.environ["APP_SECRET"] = "testsecret"
    os.environ["ADMIN_PASSWORD"] = "admin"
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    source_root = data_root / "sources" / "demo"
    source_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATA_CONTAINER_PATH", str(data_root))
    monkeypatch.setenv("INDEX_ROOTS", f"{source_root}:demo")
    monkeypatch.setenv("AUTO_INDEX_DISABLE", "1")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("METRICS_DB_PATH", str(tmp_path / "metrics.db"))

    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    monkeypatch.setattr(metrics_db, "METRICS_DB_PATH", tmp_path / "metrics.db")

    config_db.set_setting("base_data_root", str(data_root))
    app = create_app(load_config(use_env=True))
    return TestClient(app)


def test_manifest_is_served_with_expected_metadata(tmp_path, monkeypatch):
    client = build_test_client(tmp_path, monkeypatch)
    resp = client.get("/manifest.webmanifest")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/manifest+json")
    cache_header = resp.headers.get("cache-control", "")
    assert "max-age" in cache_header

    data = resp.json()
    assert data.get("name") == "Index-Suche"
    assert data.get("display") == "standalone"
    assert data.get("start_url") == "/"
    icons = {icon.get("src"): icon for icon in data.get("icons", [])}
    assert "/static/pwa/icon-192.png" in icons
    assert "/static/pwa/icon-512.png" in icons
    assert icons.get("/static/pwa/icon-192.png", {}).get("sizes") == "192x192"
    assert icons.get("/static/pwa/icon-512-maskable.png", {}).get("purpose") == "maskable"


def test_service_worker_and_icons_are_public(tmp_path, monkeypatch):
    client = build_test_client(tmp_path, monkeypatch)

    sw = client.get("/service-worker.js")
    assert sw.status_code == 200
    assert sw.headers.get("content-type", "").startswith("application/javascript")
    assert "skipWaiting" in sw.text
    cache_header = sw.headers.get("cache-control", "")
    assert "no-cache" in cache_header or "no-store" in cache_header

    icon = client.get("/static/pwa/icon-192.png")
    assert icon.status_code == 200
    assert icon.headers.get("content-type", "").startswith("image/png")
