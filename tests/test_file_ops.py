import os
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config_db
from app.config_loader import load_config
from app.db import datenbank as db
from app.db.datenbank import DocumentMeta
from app.main import create_app


def setup_env(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ops.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    os.environ["APP_SECRET"] = "secret"
    os.environ["ADMIN_PASSWORD"] = "admin"
    os.environ["AUTO_INDEX_DISABLE"] = "1"
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    os.environ["INDEX_ROOTS"] = f"{root}:Root"
    return root


def seed_document(path: Path, source: str) -> int:
    db.init_db()
    with db.get_conn() as conn:
        meta = DocumentMeta(
            source=source,
            path=str(path),
            filename=path.name,
            extension=path.suffix.lower(),
            size_bytes=path.stat().st_size,
            ctime=path.stat().st_ctime,
            mtime=path.stat().st_mtime,
            atime=None,
            owner=None,
            last_editor=None,
            content="content",
            title_or_subject=path.stem,
        )
        return db.upsert_document(conn, meta)


def test_admin_login_success(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}

    resp = client.post("/api/admin/login", json={"password": "admin"}, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("admin") is True
    assert resp.cookies.get("admin_session")
    assert data.get("file_ops_enabled") is True


def test_admin_login_fail(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}

    resp = client.post("/api/admin/login", json={"password": "wrong"}, headers=headers)
    assert resp.status_code == 401


def test_missing_admin_password(monkeypatch, tmp_path):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ops.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    os.environ["APP_SECRET"] = "secret"
    os.environ["AUTO_INDEX_DISABLE"] = "1"
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        create_app(load_config(use_env=True))


def test_delete_requires_admin(monkeypatch, tmp_path):
    root = setup_env(monkeypatch, tmp_path)
    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}
    doc_id = seed_document(file_path, "Root")

    resp = client.post(f"/api/files/{doc_id}/quarantine-delete", headers=headers)
    assert resp.status_code == 403
    assert file_path.exists()


def test_delete_requires_ready_source(monkeypatch, tmp_path):
    root = setup_env(monkeypatch, tmp_path)
    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    root.chmod(0o500)
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}
    doc_id = seed_document(file_path, "Root")
    client.post("/api/admin/login", json={"password": "admin"}, headers=headers)

    resp = client.post(f"/api/files/{doc_id}/quarantine-delete", headers=headers)
    try:
        root.chmod(0o755)
    except Exception:
        pass
    assert resp.status_code == 400
    assert file_path.exists()


def test_delete_rejects_outside_root(monkeypatch, tmp_path):
    root = setup_env(monkeypatch, tmp_path)
    file_path = tmp_path / "other" / "doc.txt"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("hello", encoding="utf-8")
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}
    doc_id = seed_document(file_path, "Root")
    client.post("/api/admin/login", json={"password": "admin"}, headers=headers)

    resp = client.post(f"/api/files/{doc_id}/quarantine-delete", headers=headers)
    assert resp.status_code == 400
    assert file_path.exists()
    with db.get_conn() as conn:
        assert db.get_document(conn, doc_id) is not None


def test_quarantine_delete_success(monkeypatch, tmp_path):
    root = setup_env(monkeypatch, tmp_path)
    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}
    doc_id = seed_document(file_path, "Root")
    login = client.post("/api/admin/login", json={"password": "admin"}, headers=headers)
    assert login.status_code == 200

    resp = client.post(f"/api/files/{doc_id}/quarantine-delete", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("removed_from_index") is True
    target = Path(data.get("quarantine_path"))
    assert target.exists()
    assert target.parent.name == date.today().isoformat()
    assert not file_path.exists()
    with db.get_conn() as conn:
        assert db.get_document(conn, doc_id) is None
