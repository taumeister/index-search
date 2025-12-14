from pathlib import Path

from app.config_loader import load_config
from app.db import datenbank as db
from app.indexer.index_lauf_service import run_index_lauf
from app.main import resolve_active_roots
from app import config_db


def test_indexer_runs(tmp_path, monkeypatch):
    # eigene DB
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    data_dir = tmp_path / "docs"
    data_dir.mkdir()
    file_path = data_dir / "hello.txt"
    file_path.write_text("hallo welt")
    monkeypatch.setenv("INDEX_ROOTS", str(data_dir))
    monkeypatch.setenv("INDEX_WORKER_COUNT", "1")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    config = load_config()
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

    monkeypatch.delenv("INDEX_ROOTS", raising=False)
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("INDEX_WORKER_COUNT", "1")
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
