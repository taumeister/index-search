from pathlib import Path

from app.config_loader import load_config
from app.db import datenbank as db
from app.indexer.index_lauf_service import run_index_lauf


def test_indexer_runs(tmp_path, monkeypatch):
    # eigene DB
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    # Config schreiben
    data_dir = tmp_path / "docs"
    data_dir.mkdir()
    file_path = data_dir / "hello.txt"
    file_path.write_text("hallo welt")

    cfg_file = tmp_path / "central_config.ini"
    cfg_file.write_text(
        f"""
[paths]
roots = {data_dir}
[indexer]
worker_count = 1
[logging]
log_dir = {tmp_path/'logs'}
        """
    )
    config = load_config(cfg_file)
    counters = run_index_lauf(config)
    assert counters["added"] == 1
    with db.get_conn() as conn:
        rows = db.search_documents(conn, "hallo")
        assert len(rows) == 1
