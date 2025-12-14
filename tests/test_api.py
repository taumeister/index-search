from pathlib import Path
import os

from fastapi.testclient import TestClient

from app.config_loader import load_config
from app.db import datenbank as db
from app.main import create_app
from app import config_db


def test_search_endpoint(tmp_path, monkeypatch):
    os.environ["APP_SECRET"] = "testsecret"
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
