import logging
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request

from app import api
from app.config_loader import CentralConfig, ensure_dirs, load_config
from app.db import datenbank as db

logging.basicConfig(level=logging.INFO)


def get_config() -> CentralConfig:
    return load_config()


def create_app(config: Optional[CentralConfig] = None) -> FastAPI:
    config = config or load_config()
    ensure_dirs(config)
    db.init_db()

    app = FastAPI(title="Index-Suche")
    templates = Jinja2Templates(directory="app/frontend/templates")
    app.mount("/static", StaticFiles(directory="app/frontend/static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "default_preview": config.ui.default_preview, "snippet_length": config.ui.snippet_length},
        )

    @app.get("/api/search")
    def search(
        q: str = Query(..., description="Suchbegriff"),
        source: Optional[str] = None,
        extension: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ):
        with db.get_conn() as conn:
            filters = {}
            if source:
                filters["source"] = source
            if extension:
                filters["extension"] = extension.lower()
            rows = db.search_documents(conn, q, limit=limit, offset=offset, filters=filters)
            return {"results": [dict(row) for row in rows]}

    @app.get("/api/document/{doc_id}")
    def document_details(doc_id: int):
        with db.get_conn() as conn:
            row = db.get_document(conn, doc_id)
            if not row:
                raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
            content = db.get_document_content(conn, doc_id)
            data = dict(row)
            data["content"] = content
            return data

    @app.get("/api/document/{doc_id}/file")
    def document_file(doc_id: int):
        with db.get_conn() as conn:
            row = db.get_document(conn, doc_id)
            if not row:
                raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
            path = Path(row["path"])
            if not path.exists():
                raise HTTPException(status_code=404, detail="Datei nicht mehr vorhanden")
            return FileResponse(path)

    @app.get("/api/admin/status")
    def admin_status():
        with db.get_conn() as conn:
            status = db.get_status(conn)
            return status

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
