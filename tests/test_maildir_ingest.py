from pathlib import Path

import pytest

from app.config_loader import load_config
from app.db import datenbank as db
from app import config_db
from app.indexer.index_lauf_service import run_index_lauf
from app.services import file_ops
import shutil


def _maildir_fixture_root() -> Path:
    return Path(__file__).parent / "fixtures" / "maildir" / ".INBOX"


def _bootstrap_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    monkeypatch.setattr(config_db, "CONFIG_DB_PATH", tmp_path / "config.db")
    config_db.set_setting("base_data_root", str(tmp_path))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("INDEX_WORKER_COUNT", "1")
    monkeypatch.setenv("DATA_CONTAINER_PATH", str(tmp_path))


def test_maildir_is_indexed(monkeypatch, tmp_path):
    _bootstrap_env(monkeypatch, tmp_path)
    target_root = tmp_path / "maildir" / ".INBOX"
    target_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_maildir_fixture_root(), target_root)
    config_db.add_root(str(target_root), "maildir", True, type_="maildir")
    cfg = load_config()
    cfg.paths.roots = [(Path(target_root), "maildir", "maildir")]
    counters = run_index_lauf(cfg)
    assert counters["added"] == 2
    with db.get_conn() as conn:
        unicorn_hits = db.search_documents(conn, "unicorn")
        assert len(unicorn_hits) == 1
        doc = unicorn_hits[0]
        assert doc["extension"] == ".eml"
        assert doc["msg_subject"] == "Hello Maildir"
        assert "alice" in (doc["msg_from"] or "").lower()
        lighthouse_hits = db.search_documents(conn, "lighthouse")
        assert len(lighthouse_hits) == 1
        html_doc = lighthouse_hits[0]
        assert html_doc["msg_subject"] == "HTML Only Mail"
        assert html_doc["msg_message_id"]


def test_maildir_read_only_guards(monkeypatch, tmp_path):
    _bootstrap_env(monkeypatch, tmp_path)
    target_root = tmp_path / "maildir" / ".INBOX"
    target_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_maildir_fixture_root(), target_root)
    config_db.add_root(str(target_root), "maildir", True, type_="maildir")
    cfg = load_config()
    cfg.paths.roots = [(Path(target_root), "maildir", "maildir")]
    counters = run_index_lauf(cfg)
    assert counters["added"] == 2
    with db.get_conn() as conn:
        doc = db.search_documents(conn, "unicorn")[0]
        doc_id = doc["id"]
    with pytest.raises(file_ops.FileOpError):
        file_ops.rename_file(doc_id, "renamed.eml")
    with pytest.raises(file_ops.FileOpError):
        file_ops.create_upload_session("maildir", "", [{"name": "x.txt", "size": 10}])
