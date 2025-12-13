import os
import pytest

from app.config_loader import load_config


def test_load_config_defaults(monkeypatch):
    for key in ["INDEX_ROOTS", "INDEX_WORKER_COUNT", "INDEX_MAX_FILE_SIZE_MB", "SMTP_HOST"]:
        monkeypatch.delenv(key, raising=False)
    cfg = load_config(use_env=False)
    assert cfg.indexer.worker_count == 2
    assert cfg.paths.roots == []
    assert cfg.smtp is None


def test_paths_with_labels(monkeypatch):
    for key in ["SMTP_HOST", "INDEX_MAX_FILE_SIZE_MB"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("INDEX_ROOTS", "/mnt/a:quelle_a,/mnt/b")
    monkeypatch.setenv("INDEX_WORKER_COUNT", "3")
    cfg = load_config(use_env=True)
    assert cfg.paths.roots[0][1] == "quelle_a"
    assert cfg.paths.roots[1][1] == "b"
    assert cfg.indexer.worker_count == 3


def test_invalid_worker_count(monkeypatch):
    for key in ["SMTP_HOST", "INDEX_ROOTS"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("INDEX_WORKER_COUNT", "0")
    with pytest.raises(Exception):
        load_config(use_env=True)
