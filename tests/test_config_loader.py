from pathlib import Path

import pytest

from app.config_loader import load_config


def test_load_config_defaults(tmp_path: Path):
    cfg_file = tmp_path / "central_config.ini"
    cfg_file.write_text("")
    cfg = load_config(cfg_file)
    assert cfg.indexer.worker_count == 2
    assert cfg.paths.roots == []
    assert cfg.smtp is None


def test_paths_with_labels(tmp_path: Path):
    cfg_file = tmp_path / "central_config.ini"
    cfg_file.write_text(
        """
[paths]
roots = /mnt/a:quelle_a,/mnt/b
[indexer]
worker_count = 3
        """
    )
    cfg = load_config(cfg_file)
    assert cfg.paths.roots[0][1] == "quelle_a"
    assert cfg.paths.roots[1][1] == "b"
    assert cfg.indexer.worker_count == 3


def test_invalid_worker_count(tmp_path: Path):
    cfg_file = tmp_path / "central_config.ini"
    cfg_file.write_text(
        """
[indexer]
worker_count = 0
        """
    )
    with pytest.raises(Exception):
        load_config(cfg_file)
