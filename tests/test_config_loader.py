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
    assert cfg.ui.search_default_mode == "standard"
    assert cfg.ui.search_prefix_minlen == 4
    assert cfg.feedback.enabled is False
    assert cfg.feedback.recipients == []


def test_paths_with_labels(monkeypatch):
    for key in ["SMTP_HOST", "INDEX_MAX_FILE_SIZE_MB", "FEEDBACK_TO", "FEEDBACK_ENABLED"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("INDEX_ROOTS", "/mnt/a:quelle_a,/mnt/b")
    monkeypatch.setenv("INDEX_WORKER_COUNT", "3")
    cfg = load_config(use_env=True)
    assert cfg.paths.roots[0][1] == "quelle_a"
    assert cfg.paths.roots[1][1] == "b"
    assert cfg.indexer.worker_count == 3
    assert cfg.ui.search_default_mode == "standard"
    assert cfg.ui.search_prefix_minlen == 4
    assert cfg.feedback.recipients == []


def test_invalid_worker_count(monkeypatch):
    for key in ["SMTP_HOST", "INDEX_ROOTS"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("INDEX_WORKER_COUNT", "0")
    with pytest.raises(Exception):
        load_config(use_env=True)


def test_search_ui_env(monkeypatch):
    for key in ["INDEX_ROOTS", "INDEX_WORKER_COUNT", "SEARCH_DEFAULT_MODE", "SEARCH_PREFIX_MINLEN"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SEARCH_DEFAULT_MODE", "strict")
    monkeypatch.setenv("SEARCH_PREFIX_MINLEN", "6")
    cfg = load_config(use_env=True)
    assert cfg.ui.search_default_mode == "strict"
    assert cfg.ui.search_prefix_minlen == 6


def test_feedback_env(monkeypatch):
    for key in ["INDEX_ROOTS", "INDEX_WORKER_COUNT", "SMTP_HOST", "FEEDBACK_ENABLED", "FEEDBACK_TO"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("FEEDBACK_ENABLED", "true")
    monkeypatch.setenv("FEEDBACK_TO", "a@example.org, b@example.org ,")
    cfg = load_config(use_env=True)
    assert cfg.feedback.enabled is True
    assert cfg.feedback.recipients == ["a@example.org", "b@example.org"]
