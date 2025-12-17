import os
from pathlib import Path

from app import config_db
from app.config_loader import load_config
from app.db import datenbank as db
from app.db.datenbank import DocumentMeta
from app.indexer.index_lauf_service import run_index_lauf
from app.main import resolve_active_roots


def setup_env(monkeypatch, tmp_path: Path, exclude: str):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    os.environ["APP_SECRET"] = "secret"
    os.environ["ADMIN_PASSWORD"] = "admin"
    os.environ["DATA_CONTAINER_PATH"] = str(tmp_path)
    root = tmp_path / "root"
    config_db.set_setting("base_data_root", str(tmp_path))
    config_db.add_root(str(root), root.name, True)
    os.environ["INDEX_EXCLUDE_DIRS"] = exclude
    os.environ["AUTO_INDEX_DISABLE"] = "1"
    root.mkdir(parents=True, exist_ok=True)
    (root / "file1.txt").write_text("hello", encoding="utf-8")
    (root / ".quarantine").mkdir(parents=True, exist_ok=True)
    (root / ".quarantine" / "deleted.txt").write_text("secret", encoding="utf-8")
    (root / ".git").mkdir(parents=True, exist_ok=True)
    (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    return root


def test_exclude_quarantine(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path, ".quarantine")
    cfg = load_config(use_env=True)
    cfg.paths.roots = resolve_active_roots(cfg)
    db.init_db()
    run_index_lauf(cfg)
    with db.get_conn() as conn:
        rows = db.search_documents(conn, "*", limit=10)
    paths = {row["path"] for row in rows}
    assert any("file1.txt" in p for p in paths)
    assert not any(".quarantine" in p for p in paths)


def test_exclude_multiple(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path, ".quarantine,.git")
    cfg = load_config(use_env=True)
    cfg.paths.roots = resolve_active_roots(cfg)
    db.init_db()
    run_index_lauf(cfg)
    with db.get_conn() as conn:
        rows = db.search_documents(conn, "*", limit=10)
    paths = {row["path"] for row in rows}
    assert any("file1.txt" in p for p in paths)
    assert not any(".quarantine" in p for p in paths)
    assert not any(".git" in p for p in paths)
