import os
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.config_loader import load_config
from app.db import datenbank as db
from app.main import create_app
from app.services import file_ops
from tests.test_file_ops import setup_env, seed_document


def create_admin_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, dict, Path]:
    root = setup_env(monkeypatch, tmp_path)
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}
    login = client.post("/api/admin/login", json={"password": "admin"}, headers=headers)
    assert login.status_code == 200
    return client, headers, root


def test_quarantine_metadata_written(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(tmp_path, monkeypatch)
    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    doc_id = seed_document(file_path, "Root")

    resp = client.post(f"/api/files/{doc_id}/quarantine-delete", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    entry_id = data.get("entry_id")
    quarantine_path = Path(data.get("quarantine_path"))
    assert entry_id
    assert quarantine_path.exists()

    with db.get_conn() as conn:
        entry = db.get_quarantine_entry(conn, entry_id)
    assert entry is not None
    assert entry["doc_id"] == doc_id
    assert entry["original_path"] == str(file_path)
    assert entry["quarantine_path"] == str(quarantine_path)
    assert entry["original_filename"] == file_path.name
    assert entry["status"] == "quarantined"
    assert entry["actor"] == "admin"
    assert entry["moved_at"]


def test_quarantine_restore_moves_back_and_updates_registry(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(tmp_path, monkeypatch)
    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    doc_id = seed_document(file_path, "Root")
    resp = client.post(f"/api/files/{doc_id}/quarantine-delete", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    entry_id = data["entry_id"]
    quarantine_path = Path(data["quarantine_path"])
    assert quarantine_path.exists()
    assert not file_path.exists()

    restore = client.post(f"/api/quarantine/{entry_id}/restore", headers=headers)
    assert restore.status_code == 200
    assert file_path.exists()
    assert not quarantine_path.exists()
    with db.get_conn() as conn:
        entry = db.get_quarantine_entry(conn, entry_id)
    assert entry["status"] == "restored"
    assert entry["restored_path"] == str(file_path)


def test_quarantine_hard_delete_removes_file_and_registry(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(tmp_path, monkeypatch)
    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    doc_id = seed_document(file_path, "Root")
    resp = client.post(f"/api/files/{doc_id}/quarantine-delete", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    entry_id = data["entry_id"]
    quarantine_path = Path(data["quarantine_path"])
    assert quarantine_path.exists()

    hard = client.post(f"/api/quarantine/{entry_id}/hard-delete", headers=headers)
    assert hard.status_code == 200
    assert not quarantine_path.exists()
    with db.get_conn() as conn:
        entry = db.get_quarantine_entry(conn, entry_id)
    assert entry["status"] == "hard_deleted"


def test_quarantine_cleanup_respects_retention(monkeypatch, tmp_path):
    monkeypatch.setenv("QUARANTINE_RETENTION_DAYS", "1")
    client, headers, root = create_admin_client(tmp_path, monkeypatch)
    old_path = root / "old.txt"
    new_path = root / "new.txt"
    old_path.write_text("old", encoding="utf-8")
    new_path.write_text("new", encoding="utf-8")
    old_id = seed_document(old_path, "Root")
    new_id = seed_document(new_path, "Root")

    old_resp = client.post(f"/api/files/{old_id}/quarantine-delete", headers=headers)
    new_resp = client.post(f"/api/files/{new_id}/quarantine-delete", headers=headers)
    old_entry = old_resp.json()["entry_id"]
    new_entry = new_resp.json()["entry_id"]
    old_quarantine = Path(old_resp.json()["quarantine_path"])
    new_quarantine = Path(new_resp.json()["quarantine_path"])
    assert old_quarantine.exists() and new_quarantine.exists()
    two_days_ago = time.time() - 2 * 86400
    os.utime(old_quarantine, (two_days_ago, two_days_ago))

    summary = file_ops.run_cleanup_now(now=datetime.now(timezone.utc))
    assert summary["deleted"] == 1
    assert not old_quarantine.exists()
    assert new_quarantine.exists()
    with db.get_conn() as conn:
        old_entry_row = db.get_quarantine_entry(conn, old_entry)
        new_entry_row = db.get_quarantine_entry(conn, new_entry)
    assert old_entry_row["status"] == "cleanup_deleted"
    assert new_entry_row["status"] == "quarantined"


def test_cleanup_never_touches_outside_quarantine(monkeypatch, tmp_path):
    monkeypatch.setenv("QUARANTINE_RETENTION_DAYS", "0")
    client, headers, root = create_admin_client(tmp_path, monkeypatch)
    outside = root / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    old_time = time.time() - 5 * 86400
    os.utime(outside, (old_time, old_time))

    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    doc_id = seed_document(file_path, "Root")
    resp = client.post(f"/api/files/{doc_id}/quarantine-delete", headers=headers)
    quarantine_path = Path(resp.json()["quarantine_path"])
    assert quarantine_path.exists()
    os.utime(quarantine_path, (old_time, old_time))

    file_ops.run_cleanup_now(now=datetime.now(timezone.utc))
    assert outside.exists()


def test_quarantine_list_requires_admin(monkeypatch, tmp_path):
    root = setup_env(monkeypatch, tmp_path)
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}

    resp = client.get("/api/quarantine/list", headers=headers)
    assert resp.status_code == 403


def test_missing_quarantine_entry_is_cleaned_up(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(tmp_path, monkeypatch)
    file_path = root / "ghost.txt"
    file_path.write_text("ghost", encoding="utf-8")
    doc_id = seed_document(file_path, "Root")
    resp = client.post(f"/api/files/{doc_id}/quarantine-delete", headers=headers)
    entry_id = resp.json()["entry_id"]
    quarantine_path = Path(resp.json()["quarantine_path"])
    assert quarantine_path.exists()
    quarantine_path.unlink()

    resp_list = client.get("/api/quarantine/list", headers=headers)
    assert resp_list.status_code == 200
    entries = resp_list.json().get("entries", [])
    assert all(e.get("id") != entry_id for e in entries)
    with db.get_conn() as conn:
        entry = db.get_quarantine_entry(conn, entry_id)
    assert entry["status"] == "cleanup_deleted"


def test_hard_delete_missing_file_marks_clean(monkeypatch, tmp_path):
    client, headers, root = create_admin_client(tmp_path, monkeypatch)
    file_path = root / "miss.txt"
    file_path.write_text("missing", encoding="utf-8")
    doc_id = seed_document(file_path, "Root")
    resp = client.post(f"/api/files/{doc_id}/quarantine-delete", headers=headers)
    entry_id = resp.json()["entry_id"]
    quarantine_path = Path(resp.json()["quarantine_path"])
    assert quarantine_path.exists()
    quarantine_path.unlink()

    hard = client.post(f"/api/quarantine/{entry_id}/hard-delete", headers=headers)
    assert hard.status_code == 200
    body = hard.json()
    assert body.get("status") == "missing"
    with db.get_conn() as conn:
        entry = db.get_quarantine_entry(conn, entry_id)
    assert entry["status"] == "cleanup_deleted"
