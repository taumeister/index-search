import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config_db
from app.config_loader import load_config
from app.db import datenbank as db
from app.indexer.index_lauf_service import run_index_lauf
from app.main import create_app
from app.services import file_ops
from tests.test_file_ops import setup_env, seed_document


def create_admin_client(monkeypatch, tmp_path: Path) -> tuple[TestClient, dict, Path]:
    root = setup_env(monkeypatch, tmp_path)
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}
    login = client.post("/api/admin/login", json={"password": "admin"}, headers=headers)
    assert login.status_code == 200
    return client, headers, root


def test_index_run_rejected_when_source_unready(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(monkeypatch, tmp_path)
    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    seed_document(file_path, "Root")
    root.chmod(0o000)
    try:
        resp = client.post("/api/admin/index/run", headers=headers)
        assert resp.status_code == 503
        with db.get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        assert count == 1
    finally:
        root.chmod(0o755)


def test_auto_index_like_run_skips_prune_on_empty_source(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    os.environ["APP_SECRET"] = "secret"
    os.environ["ADMIN_PASSWORD"] = "admin"
    os.environ["AUTO_INDEX_DISABLE"] = "1"
    os.environ["DATA_CONTAINER_PATH"] = str(tmp_path)
    config_db.set_setting("base_data_root", str(tmp_path))
    root = tmp_path / "root"
    root.mkdir()
    config_db.add_root(str(root), "Root", True)
    file_path = root / "doc.txt"
    file_path.write_text("hi", encoding="utf-8")
    cfg = load_config(use_env=True)
    cfg.paths.roots = [(root, "Root")]
    db.init_db()
    run_index_lauf(cfg)
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    offline_store = tmp_path / "offline"
    root.rename(offline_store)
    empty_root = tmp_path / "root"
    empty_root.mkdir()
    cfg.paths.roots = [(empty_root, "Root")]
    counters = run_index_lauf(cfg)
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    assert counters["removed"] == 0


def test_quarantine_operations_fail_when_not_writable(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(monkeypatch, tmp_path)
    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    doc_id = seed_document(file_path, "Root")
    qdir = root / ".quarantine"
    qdir.mkdir(parents=True, exist_ok=True)
    qdir.chmod(0o500)
    try:
        resp_list = client.get("/api/quarantine/list", headers=headers)
        assert resp_list.status_code == 503
        resp_delete = client.post(f"/api/files/{doc_id}/quarantine-delete", headers=headers)
        assert resp_delete.status_code == 503
        assert file_path.exists()
    finally:
        qdir.chmod(0o755)


def test_safe_delete_blocks_outside_quarantine(monkeypatch, tmp_path):
    root = setup_env(monkeypatch, tmp_path)
    quarantine_dir = root / ".quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(file_ops.FileOpError):
        file_ops.safe_delete(outside, quarantine_dir)
    link = quarantine_dir / "link"
    link.symlink_to(outside)
    with pytest.raises(file_ops.FileOpError):
        file_ops.safe_delete(link, quarantine_dir)


def test_index_readiness_blocks_on_unreadable_files(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(monkeypatch, tmp_path)
    bad_file = root / "locked.pdf"
    bad_file.write_text("secret", encoding="utf-8")
    seed_document(bad_file, "Root")
    bad_file.chmod(0o000)
    try:
        resp = client.post("/api/admin/index/run", headers=headers)
        assert resp.status_code == 503
    finally:
        bad_file.chmod(0o644)


def test_quarantine_not_created_when_root_missing(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(monkeypatch, tmp_path)
    offline = root.parent / "offline"
    root.rename(offline)
    root.mkdir()
    resp = client.get("/api/quarantine/list", headers=headers)
    assert resp.status_code == 503
    assert not (root / ".quarantine").exists()
