import pytest

from app.db import datenbank as db
from app.search_modes import SearchMode, build_search_plan


@pytest.fixture
def db_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    db.init_db()
    counter = {"i": 0}

    def add_doc(content: str, *, title: str | None = None, filename: str | None = None):
        counter["i"] += 1
        name = filename or f"doc{counter['i']}.txt"
        meta = db.DocumentMeta(
            source="test",
            path=str(tmp_path / name),
            filename=name,
            extension=".txt",
            size_bytes=1,
            ctime=1.0,
            mtime=1.0,
            atime=1.0,
            owner=None,
            last_editor=None,
            content=content,
            title_or_subject=title or name,
        )
        with db.get_conn() as conn:
            db.upsert_document(conn, meta)

    def run_search(query: str, mode: SearchMode = SearchMode.STRICT, prefix_min_len: int = 4):
        plan = build_search_plan(query, mode, prefix_min_len)
        assert plan.fts_query
        with db.get_conn() as conn:
            return db.search_documents(conn, plan.fts_query, limit=50)

    return add_doc, run_search


def test_strict_does_not_match_prefix(db_setup):
    add_doc, run_search = db_setup
    add_doc("Das ist ein Test", title="Test", filename="exact.txt")
    add_doc("Enthält Testament als Wort", title="Testament", filename="prefix.txt")

    rows = run_search("Test", SearchMode.STRICT)
    names = {row["filename"] for row in rows}
    assert "exact.txt" in names
    assert "prefix.txt" not in names


def test_standard_prefix_minlen(db_setup):
    add_doc, run_search = db_setup
    add_doc("Testament im Inhalt", title="Testament", filename="longprefix.txt")
    add_doc("Te im Inhalt", title="Te", filename="short.txt")

    rows = run_search("test", SearchMode.STANDARD, prefix_min_len=4)
    names = {row["filename"] for row in rows}
    assert "longprefix.txt" in names
    assert "short.txt" not in names

    rows_short = run_search("te", SearchMode.STANDARD, prefix_min_len=4)
    names_short = {row["filename"] for row in rows_short}
    assert "longprefix.txt" not in names_short
    assert "short.txt" in names_short


def test_strict_and_across_fields(db_setup):
    add_doc, run_search = db_setup
    add_doc("Hier steht test im Inhalt", title="Thomas", filename="mixed.txt")
    add_doc("Nur test ohne Namen", title="KeinName", filename="only-test.txt")

    rows = run_search("test thomas", SearchMode.STRICT)
    names = {row["filename"] for row in rows}
    assert "mixed.txt" in names
    assert "only-test.txt" not in names


def test_loose_or_matches_single_token(db_setup):
    add_doc, run_search = db_setup
    add_doc("Nur test hier", title="Datei", filename="test-only.txt")
    add_doc("Enthält thomas", title="Thomas", filename="thomas-only.txt")

    rows = run_search("test thomas", SearchMode.LOOSE)
    names = {row["filename"] for row in rows}
    assert "test-only.txt" in names
    assert "thomas-only.txt" in names
