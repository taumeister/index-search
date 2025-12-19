import os

from fastapi.testclient import TestClient

from app.config_loader import load_config
from app.main import create_app
from tests.test_file_ops import seed_document, setup_env


def test_always_on_enables_file_ops_without_login(monkeypatch, tmp_path):
    root = setup_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ADMIN_ALWAYS_ON", "1")
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}

    file_path = root / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")
    doc_id = seed_document(file_path, "Root")

    resp = client.post(f"/api/files/{doc_id}/rename", json={"new_name": "renamed.txt"}, headers=headers)
    assert resp.status_code == 200
    assert (root / "renamed.txt").exists()


def test_admin_status_reports_always_on(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ADMIN_ALWAYS_ON", "1")
    app = create_app(load_config(use_env=True))
    client = TestClient(app)
    headers = {"X-App-Secret": os.environ["APP_SECRET"]}

    resp = client.get("/api/admin/status", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("admin") is True
    assert data.get("admin_always_on") is True
