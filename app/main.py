import logging
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import mimetypes
import threading
import os

from app import api
from app import config_db
from app.config_loader import CentralConfig, ensure_dirs, load_config
from app.db import datenbank as db
from app.indexer.index_lauf_service import run_index_lauf

logging.basicConfig(level=logging.INFO)
index_lock = threading.Lock()


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

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        return templates.TemplateResponse("dashboard.html", {"request": request})

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
        db.init_db()
        with db.get_conn() as conn:
            status = db.get_status(conn)
            return status

    @app.get("/api/admin/roots")
    def admin_roots():
        roots = [
            {"id": rid, "path": path, "label": label, "active": active}
            for path, label, rid, active in config_db.list_roots(active_only=False)
        ]
        return {"roots": roots, "base_data_root": config_db.get_setting("base_data_root", "/data")}

    @app.post("/api/admin/roots")
    def add_root(path: str = Query(...), label: Optional[str] = Query(None), active: bool = Query(True)):
        base = config_db.get_setting("base_data_root", "/data")
        if base and not str(path).startswith(base):
            raise HTTPException(status_code=400, detail=f"Pfad muss unter {base} liegen")
        rid = config_db.add_root(path, label, active)
        return {"id": rid}

    @app.delete("/api/admin/roots/{root_id}")
    def delete_root(root_id: int):
        config_db.delete_root(root_id)
        return {"status": "ok"}

    @app.post("/api/admin/roots/{root_id}/activate")
    def activate_root(root_id: int, active: bool = Query(True)):
        config_db.update_root_active(root_id, active)
        return {"status": "ok"}

    def _start_index(full_reset: bool = False) -> str:
        if not index_lock.acquire(blocking=False):
            return "busy"
        def runner():
            try:
                cfg = load_config()
                run_index_lauf(cfg)
            finally:
                index_lock.release()
        threading.Thread(target=runner, daemon=True).start()
        return "started"

    @app.post("/api/admin/index/run")
    def trigger_index(full_reset: bool = Query(False)):
        status = _start_index(full_reset)
        if status == "busy":
            return JSONResponse({"status": "busy"}, status_code=409)
        return {"status": status}

    @app.post("/api/admin/index/reset")
    def reset_index():
        if not index_lock.acquire(blocking=False):
            return JSONResponse({"status": "busy"}, status_code=409)
        try:
            for suffix in ["data/index.db", "data/index.db-wal", "data/index.db-shm"]:
                p = Path(suffix)
                if p.exists():
                    p.unlink()
            db.init_db()
        finally:
            index_lock.release()
        return {"status": "reset"}

    @app.post("/api/admin/index/stop")
    def stop_index():
        # Not implemented (placeholder)
        return JSONResponse({"status": "not_implemented"}, status_code=501)

    @app.get("/api/admin/preflight")
    def preflight():
        cfg = load_config()
        exts = {".pdf": 0, ".rtf": 0, ".msg": 0, ".txt": 0}
        for root, _label in cfg.paths.roots:
            for dirpath, _, filenames in os.walk(root):
                for name in filenames:
                    s = Path(name).suffix.lower()
                    if s in exts:
                        exts[s] += 1
        return {"counts": exts, "roots": [str(r[0]) for r in cfg.paths.roots]}

    @app.get("/api/admin/errors")
    def admin_errors(limit: int = 50, offset: int = 0):
        db.init_db()
        with db.get_conn() as conn:
            rows = db.list_errors(conn, limit=limit, offset=offset)
            total = db.error_count(conn)
            return {"errors": [dict(r) for r in rows], "total": total}

    def list_children(path: Path) -> list:
        try:
            return [
                {"name": entry.name, "path": str(entry), "has_children": any(child.is_dir() for child in entry.iterdir())}
                for entry in sorted([e for e in path.iterdir() if e.is_dir()])
            ]
        except Exception:
            return []

    @app.get("/api/admin/tree")
    def admin_tree(parent: Optional[str] = Query(None)):
        base_root = Path(config_db.get_setting("base_data_root", "/data"))
        if not base_root.exists():
            return {"base": str(base_root), "children": []}
        target = Path(parent) if parent else base_root
        return {"base": str(base_root), "parent": str(target), "children": list_children(target)}

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
