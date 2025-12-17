from app.db import datenbank as db


def test_init_and_upsert(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    db.init_db()
    meta = db.DocumentMeta(
        source="quelle",
        path=str(tmp_path / "file.txt"),
        filename="file.txt",
        extension=".txt",
        size_bytes=10,
        ctime=1.0,
        mtime=1.0,
        atime=1.0,
        owner=None,
        last_editor=None,
        content="hello world",
        title_or_subject="file",
    )
    with db.get_conn() as conn:
        doc_id = db.upsert_document(conn, meta)
        assert doc_id == 1
        rows = db.search_documents(conn, "hello")
        assert len(rows) == 1
        assert rows[0]["filename"] == "file.txt"


def test_delete_documents_by_source(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "index.db")
    db.init_db()
    meta_a = db.DocumentMeta(
        source="A",
        path="a.txt",
        filename="a.txt",
        extension=".txt",
        size_bytes=1,
        ctime=1.0,
        mtime=1.0,
        atime=None,
        owner=None,
        last_editor=None,
        content="a",
        title_or_subject="a",
    )
    meta_b = db.DocumentMeta(
        source="B",
        path="b.txt",
        filename="b.txt",
        extension=".txt",
        size_bytes=1,
        ctime=1.0,
        mtime=1.0,
        atime=None,
        owner=None,
        last_editor=None,
        content="b",
        title_or_subject="b",
    )
    with db.get_conn() as conn:
        db.upsert_document(conn, meta_a)
        db.upsert_document(conn, meta_b)
        removed = db.delete_documents_by_source(conn, ["B"])
        assert removed == 1
        paths = [row["path"] for row in conn.execute("SELECT path FROM documents").fetchall()]
        assert paths == ["a.txt"]
