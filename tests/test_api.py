from pathlib import Path

from fastapi.testclient import TestClient

from app.config_loader import load_config
from app.db import datenbank as db
from app.main import create_app


def test_search_endpoint(tmp_path, monkeypatch):
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

    resp = client.get("/api/search", params={"q": "suche"})
    assert resp.status_code == 200
    assert resp.json()["results"]
