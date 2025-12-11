import logging
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
import mimetypes

from app import api
from app.config_loader import CentralConfig, ensure_dirs, load_config
from app.db import datenbank as db

logging.basicConfig(level=logging.INFO)


def get_config() -> CentralConfig:
    return load_config()


def build_match_query(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return "*"
    tokens = []
    for part in raw.replace('"', " ").split():
        if not part:
            continue
        safe = part.replace('"', "")
        if safe:
            tokens.append(f"{safe}*")
    return " AND ".join(tokens) if tokens else "*"


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

    @app.get("/viewer", response_class=HTMLResponse)
    def viewer(request: Request, id: int = Query(...)):
        return templates.TemplateResponse("viewer.html", {"request": request, "doc_id": id})

    @app.get("/api/search")
    def search(
        q: str = Query("", description="Suchbegriff"),
        source: Optional[str] = None,
        extension: Optional[str] = None,
        time_filter: Optional[str] = None,
        sort_key: Optional[str] = None,
        sort_dir: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        with db.get_conn() as conn:
            filters = {}
            if source:
                filters["source"] = source
            if extension:
                filters["extension"] = extension.lower()
            if time_filter:
                filters["time_filter"] = time_filter
            rows = db.search_documents(
                conn,
                build_match_query(q),
                limit=limit,
                offset=offset,
                filters=filters,
                sort_key=sort_key,
                sort_dir=sort_dir,
            )
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
    def document_file(doc_id: int, download: bool = Query(False, description="Download erzwingen")):
        with db.get_conn() as conn:
            row = db.get_document(conn, doc_id)
            if not row:
                raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
            path = Path(row["path"])
            if not path.exists():
                raise HTTPException(status_code=404, detail="Datei nicht mehr vorhanden")
            media_type, _ = mimetypes.guess_type(path.name)
            disposition = "attachment" if download else "inline"
            headers = {"Content-Disposition": f'{disposition}; filename="{path.name}"'}
            return FileResponse(path, media_type=media_type, headers=headers)

    @app.get("/api/admin/status")
    def admin_status():
        with db.get_conn() as conn:
            status = db.get_status(conn)
            return status

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
