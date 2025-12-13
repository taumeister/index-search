import os
from pathlib import Path

import pytest

from app.config_loader import load_config


def test_load_config_defaults(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("INDEX_ROOTS", raising=False)
    monkeypatch.delenv("INDEX_WORKER_COUNT", raising=False)
    cfg = load_config(tmp_path / "central_config.ini")
    assert cfg.indexer.worker_count == 2
    assert cfg.paths.roots == []
    assert cfg.smtp is None


def test_paths_with_labels(monkeypatch):
    monkeypatch.setenv("INDEX_ROOTS", "/mnt/a:quelle_a,/mnt/b")
    monkeypatch.setenv("INDEX_WORKER_COUNT", "3")
    cfg = load_config()
    assert cfg.paths.roots[0][1] == "quelle_a"
    assert cfg.paths.roots[1][1] == "b"
    assert cfg.indexer.worker_count == 3


def test_invalid_worker_count(monkeypatch):
    monkeypatch.setenv("INDEX_WORKER_COUNT", "0")
    with pytest.raises(Exception):
        load_config()
