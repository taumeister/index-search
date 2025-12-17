import os
from pathlib import Path

from fastapi.testclient import TestClient

from app import config_db
from app.db import datenbank as db
from app.config_loader import load_config
from app.db.datenbank import DocumentMeta
from app.main import create_app


def setup_env(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    os.environ["ADMIN_PASSWORD"] = "admin"
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
    os.environ["APP_SECRET"] = "secret"
    os.environ["DATA_CONTAINER_PATH"] = str(tmp_path)
    root1 = tmp_path / "src1"
    root2 = tmp_path / "src2"
    root1.mkdir(parents=True, exist_ok=True)
    root2.mkdir(parents=True, exist_ok=True)
    config_db.set_setting("base_data_root", str(tmp_path))
    config_db.add_root(str(root1), "Test 1", True)
    config_db.add_root(str(root2), "Test 2", True)


def seed_documents(tmp_path: Path):
    db.init_db()
    with db.get_conn() as conn:
        meta1 = DocumentMeta(
            source="Test 1",
            path=str(tmp_path / "src1" / "a.txt"),
            filename="a.txt",
            extension=".txt",
            size_bytes=10,
            ctime=1.0,
            mtime=1.0,
            atime=None,
            owner=None,
            last_editor=None,
            content="alpha beta",
            title_or_subject="alpha",
        )
        meta2 = DocumentMeta(
            source="Test 2",
            path=str(tmp_path / "src2" / "b.txt"),
            filename="b.txt",
            extension=".txt",
            size_bytes=12,
            ctime=1.0,
            mtime=1.0,
            atime=None,
            owner=None,
            last_editor=None,
            content="alpha gamma",
            title_or_subject="alpha",
        )
        db.upsert_document(conn, meta1)
        db.upsert_document(conn, meta2)


def test_sources_filter(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    seed_documents(tmp_path)
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}

    resp_all = client.get("/api/search", params={"q": "alpha"}, headers=headers)
    assert resp_all.status_code == 200
    results_all = resp_all.json()["results"]
    assert len(results_all) == 2

    resp_single = client.get(
        "/api/search",
        params=[("q", "alpha"), ("source_labels", "Test 1")],
        headers=headers,
    )
    assert resp_single.status_code == 200
    results_single = resp_single.json()["results"]
    assert len(results_single) == 1
    assert results_single[0]["source"] == "Test 1"

    resp_multi = client.get(
        "/api/search",
        params=[("q", "alpha"), ("source_labels", "Test 1"), ("source_labels", "Test 2")],
        headers=headers,
    )
    assert resp_multi.status_code == 200
    results_multi = resp_multi.json()["results"]
    assert len(results_multi) == 2

    resp_sources = client.get("/api/sources", headers=headers)
    assert resp_sources.status_code == 200
    labels = resp_sources.json().get("labels")
    assert labels == ["Test 1", "Test 2"]
