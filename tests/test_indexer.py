from pathlib import Path

import pytest

from app.config_loader import load_config
from app.db import datenbank as db
from app.indexer.index_lauf_service import run_index_lauf
from app.main import resolve_active_roots
from app import config_db


def test_indexer_runs(tmp_path, monkeypatch):
    # eigene DB
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    config_db.set_setting("base_data_root", str(tmp_path))
    data_dir = tmp_path / "docs"
    data_dir.mkdir()
    config_db.add_root(str(data_dir), "docs", True)
    file_path = data_dir / "hello.txt"
    file_path.write_text("hallo welt")
    monkeypatch.setenv("INDEX_WORKER_COUNT", "1")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DATA_CONTAINER_PATH", str(tmp_path))
    config = load_config()
    config.paths.roots = resolve_active_roots(config)
    counters = run_index_lauf(config)
    assert counters["added"] == 1
    with db.get_conn() as conn:
        rows = db.search_documents(conn, "hallo")
        assert len(rows) == 1


def test_indexer_uses_config_db_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    base = tmp_path / "data"
    base.mkdir()
    target = base / "projekte" / "archiv" / "2024" / "q4"
    target.mkdir(parents=True)
    other = base / "projekte" / "sonstiges"
    other.mkdir(parents=True)
    (target / "hit.txt").write_text("ich bin drin")
    (other / "miss.txt").write_text("sollte ignoriert werden")

    config_db.set_setting("base_data_root", str(base))
    config_db.add_root(str(target), "archiv", True)
    config_db.add_root(str(other), "ignore", False)

    monkeypatch.delenv("INDEX_ROOTS", raising=False)
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("INDEX_WORKER_COUNT", "1")
    monkeypatch.setenv("DATA_CONTAINER_PATH", str(base))
    config = load_config()
    config.paths.roots = resolve_active_roots(config)

    counters = run_index_lauf(config)
    assert counters["added"] == 1
    with db.get_conn() as conn:
        rows = db.search_documents(conn, "drin")
        assert len(rows) == 1
        assert rows[0]["path"].startswith(str(target))
        miss = db.search_documents(conn, "sollte")
        assert len(miss) == 0


def test_indexer_rejects_root_base(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    config_db.set_setting("base_data_root", str(tmp_path))
    docs = tmp_path / "docs"
    docs.mkdir()
    config_db.add_root(str(docs), "docs", True)
    monkeypatch.setenv("DATA_CONTAINER_PATH", "/")
    config = load_config()
    with pytest.raises(ValueError):
        resolve_active_roots(config)


def test_indexer_rejects_root_outside_base(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    base = tmp_path / "base"
    base.mkdir()
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    monkeypatch.setenv("DATA_CONTAINER_PATH", str(base))
    config_db.set_setting("base_data_root", str(base))
    config_db.add_root(str(outside_root), "outside", True)
    config = load_config()
    with pytest.raises(ValueError):
        resolve_active_roots(config)


def test_resolve_roots_prefers_db_and_errors_when_none_active(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    base = tmp_path / "base"
    base.mkdir()
    config_db.set_setting("base_data_root", str(base))
    env_root = tmp_path / "envroot"
    env_root.mkdir()
    config_db.add_root(str(env_root), "envroot", active=False)
    monkeypatch.setenv("DATA_CONTAINER_PATH", str(base))
    cfg = load_config()
    with pytest.raises(ValueError):
        resolve_active_roots(cfg)


def test_resolve_roots_skips_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    base = tmp_path / "data"
    base.mkdir()
    existing = base / "ok"
    missing = base / "missing"
    existing.mkdir(parents=True)
    config_db.set_setting("base_data_root", str(base))
    config_db.add_root(str(existing), "ok", True)
    config_db.add_root(str(missing), "gone", True)
    cfg = load_config()
    roots = resolve_active_roots(cfg)
    assert roots == [(existing.resolve(), "ok")]
