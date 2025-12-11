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
