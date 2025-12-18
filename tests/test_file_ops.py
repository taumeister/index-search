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
from app.services import file_ops


def setup_env(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ops.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    os.environ["APP_SECRET"] = "secret"
    os.environ["ADMIN_PASSWORD"] = "admin"
    os.environ["AUTO_INDEX_DISABLE"] = "1"
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    os.environ["DATA_CONTAINER_PATH"] = str(root)
    config_db.set_setting("base_data_root", str(tmp_path))
    config_db.add_root(str(root), "Root", True)
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


def create_admin_client(monkeypatch, tmp_path: Path) -> tuple[TestClient, dict, Path]:
    root = setup_env(monkeypatch, tmp_path)
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}
    login = client.post("/api/admin/login", json={"password": "admin"}, headers=headers)
    assert login.status_code == 200
    return client, headers, root


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
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}
    resp = client.post("/api/admin/login", json={"password": "admin"}, headers=headers)
    assert resp.status_code == 200


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
    assert resp.status_code == 503
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


def test_rename_requires_admin(monkeypatch, tmp_path):
    root = setup_env(monkeypatch, tmp_path)
    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}
    doc_id = seed_document(file_path, "Root")

    resp = client.post(f"/api/files/{doc_id}/rename", json={"new_name": "renamed.txt"}, headers=headers)
    assert resp.status_code == 403
    assert file_path.exists()


def test_rename_rejects_invalid_name(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(monkeypatch, tmp_path)
    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    doc_id = seed_document(file_path, "Root")

    resp = client.post(f"/api/files/{doc_id}/rename", json={"new_name": "bad/name.txt"}, headers=headers)
    assert resp.status_code == 400
    assert file_path.exists()

    resp_ext = client.post(f"/api/files/{doc_id}/rename", json={"new_name": "doc.pdf"}, headers=headers)
    assert resp_ext.status_code == 400
    assert file_path.exists()


def test_rename_conflict_rejected(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(monkeypatch, tmp_path)
    original = root / "one.txt"
    other = root / "two.txt"
    original.write_text("a", encoding="utf-8")
    other.write_text("b", encoding="utf-8")
    doc_id = seed_document(original, "Root")
    seed_document(other, "Root")

    resp = client.post(f"/api/files/{doc_id}/rename", json={"new_name": "two.txt"}, headers=headers)
    assert resp.status_code == 409
    assert original.exists()
    assert other.exists()


def test_rename_success_with_backup(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(monkeypatch, tmp_path)
    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    doc_id = seed_document(file_path, "Root")

    resp = client.post(f"/api/files/{doc_id}/rename", json={"new_name": "renamed.txt"}, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    new_path = Path(data.get("new_path"))
    backup_path = Path(data.get("backup_path"))
    assert not file_path.exists()
    assert new_path.exists()
    assert backup_path.exists()
    assert backup_path.name.endswith(f"__{file_path.name}")
    assert backup_path.parent.parent.name == date.today().isoformat()
    with db.get_conn() as conn:
        row = db.get_document(conn, doc_id)
    assert row is not None
    assert row["path"] == str(new_path)
    assert row["filename"] == "renamed.txt"
    assert row["extension"] == ".txt"


def test_rename_rollback_keeps_original(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(monkeypatch, tmp_path)
    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    doc_id = seed_document(file_path, "Root")

    def boom(*_args, **_kwargs):
        raise RuntimeError("copy failed")

    monkeypatch.setattr(file_ops, "_copy_file_with_fsync", boom)
    resp = client.post(f"/api/files/{doc_id}/rename", json={"new_name": "renamed.txt"}, headers=headers)
    assert resp.status_code == 500
    assert file_path.exists()
    assert not (root / "renamed.txt").exists()
    quarantine_dir = root / ".quarantine"
    if quarantine_dir.exists():
        matches = list(quarantine_dir.rglob("doc.txt"))
        assert not matches


def test_move_rejects_deleted_target_source(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(monkeypatch, tmp_path)
    other = root.parent / "other"
    other.mkdir(parents=True)
    config_db.add_root(str(other), "Other", True)
    file_ops.refresh_quarantine_state()

    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    doc_id = seed_document(file_path, "Root")
    config_db.delete_root(next(r[2] for r in config_db.list_roots(active_only=False) if r[1] == "Other"))
    file_ops.refresh_quarantine_state()

    resp = client.post(
        f"/api/files/{doc_id}/move",
        json={"target_dir": "", "target_source": "Other"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "Quelle nicht verfügbar" in resp.json().get("detail", "")


def test_admin_ops_work_with_one_ready_one_missing_root(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(monkeypatch, tmp_path)
    missing = root.parent / "missing"
    config_db.add_root(str(missing), "Missing", True)
    file_ops.refresh_quarantine_state()

    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    doc_id = seed_document(file_path, "Root")

    resp = client.post(f"/api/files/{doc_id}/rename", json={"new_name": "renamed.txt"}, headers=headers)
    assert resp.status_code == 200
    assert (root / "renamed.txt").exists()
    assert not file_path.exists()


def test_quarantine_delete_rejects_symlink_outside(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(monkeypatch, tmp_path)
    link_path = root / "hosts_link"
    link_path.symlink_to(Path("/etc/hosts"))
    doc_id = seed_document(link_path, "Root")

    resp = client.post(f"/api/files/{doc_id}/quarantine-delete", headers=headers)
    assert resp.status_code == 400
    assert link_path.exists()
