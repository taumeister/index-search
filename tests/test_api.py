from pathlib import Path
import os

from fastapi.testclient import TestClient

from app.config_loader import load_config
from app.db import datenbank as db
from app.main import create_app
from app import config_db
from app import index_runner


def test_search_endpoint(tmp_path, monkeypatch):
    os.environ["APP_SECRET"] = "testsecret"
    os.environ["ADMIN_PASSWORD"] = "admin"
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "api.db")
    cfg_file = tmp_path / "central_config.ini"
    cfg_file.write_text(
        """
[paths]
roots =
[logging]
log_dir = logs
        """
    )
    config = load_config(cfg_file)
    app = create_app(config)
    client = TestClient(app)
    # fülle DB
    meta = db.DocumentMeta(
        source="test",
        path=str(tmp_path / "d.txt"),
        filename="d.txt",
        extension=".txt",
        size_bytes=1,
        ctime=1.0,
        mtime=1.0,
        atime=1.0,
        owner=None,
        last_editor=None,
        content="suche mich",
        title_or_subject="d",
    )
    with db.get_conn() as conn:
        db.upsert_document(conn, meta)

    resp = client.get(
        "/api/search",
        params={"q": "suche"},
        headers={"X-App-Secret": os.environ["APP_SECRET"]},
    )
    assert resp.status_code == 200
    assert resp.json()["results"]


def test_add_root_validation(tmp_path, monkeypatch):
    os.environ["APP_SECRET"] = "testsecret"
    os.environ["ADMIN_PASSWORD"] = "admin"
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "api.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    base = tmp_path / "data"
    base.mkdir()
    config_db.set_setting("base_data_root", str(base))
    client = TestClient(create_app())

    # außerhalb der Basis
    resp = client.post(
        "/api/admin/roots",
        params={"path": str(tmp_path / "other"), "label": "bad"},
        headers={"X-App-Secret": os.environ["APP_SECRET"]},
    )
    assert resp.status_code == 400

    # nicht existent innerhalb der Basis
    resp = client.post(
        "/api/admin/roots",
        params={"path": str(base / "missing"), "label": "missing"},
        headers={"X-App-Secret": os.environ["APP_SECRET"]},
    )
    assert resp.status_code == 400

    # gültig
    target = base / "projekte" / "archiv"
    target.mkdir(parents=True)
    resp = client.post(
        "/api/admin/roots",
        params={"path": str(target), "label": "archiv"},
        headers={"X-App-Secret": os.environ["APP_SECRET"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("id")


def test_reset_index_clears_without_roots(tmp_path, monkeypatch):
    os.environ["APP_SECRET"] = "testsecret"
    os.environ["ADMIN_PASSWORD"] = "admin"
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    base = tmp_path / "data_root"
    base.mkdir()
    config_db.set_setting("base_data_root", str(base))
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}
    index_file = Path(db.DB_PATH)
    assert index_file.exists()
    assert index_file.exists()
    resp = client.post("/api/admin/index/reset", headers=headers)
    assert resp.status_code == 200
    assert resp.json().get("status") == "cleared"
    assert not index_file.exists()
    status = client.get("/api/admin/indexer_status", headers=headers)
    assert status.status_code == 200
    data = status.json()
    assert data.get("run_id") is None
    assert data.get("live") in (None, {})
    assert data.get("last_run") is None


def test_admin_status_handles_missing_root(tmp_path, monkeypatch):
    os.environ["APP_SECRET"] = "testsecret"
    os.environ["ADMIN_PASSWORD"] = "admin"
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    base = tmp_path / "base"
    base.mkdir()
    config_db.set_setting("base_data_root", str(base))
    missing = base / "missing_root"
    config_db.add_root(str(missing), "missing", True)
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}

    resp = client.get("/api/admin/status", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("file_ops_enabled") in (False, True)
    # Es sollte nicht crashen, auch wenn Root fehlt
    assert "quarantine_ready_sources" in data


def test_sources_follow_active_roots(tmp_path, monkeypatch):
    os.environ["APP_SECRET"] = "testsecret"
    os.environ["ADMIN_PASSWORD"] = "admin"
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    base = tmp_path / "data"
    base.mkdir()
    config_db.set_setting("base_data_root", str(base))
    root1 = base / "r1"
    root2 = base / "r2"
    root1.mkdir(parents=True)
    root2.mkdir(parents=True)
    id1 = config_db.add_root(str(root1), "R1", True)
    id2 = config_db.add_root(str(root2), "R2", True)
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}

    resp = client.get("/api/sources", headers=headers)
    assert resp.status_code == 200
    labels = set(resp.json().get("labels", []))
    assert labels == {"R1", "R2"}

    client.delete(f"/api/admin/roots/{id2}", headers=headers)
    resp2 = client.get("/api/sources", headers=headers)
    assert resp2.status_code == 200
    labels2 = set(resp2.json().get("labels", []))
    assert labels2 == {"R1"}
