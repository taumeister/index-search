from pathlib import Path

from app.config_loader import load_config
from app.db import datenbank as db
from app.indexer.index_lauf_service import run_index_lauf


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
