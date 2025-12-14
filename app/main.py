import logging
from pathlib import Path
from typing import Optional, Dict, Any

import uvicorn
import secrets
from fastapi import Cookie, Depends, FastAPI, HTTPException, Header, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import mimetypes
import threading
import os
import time

from app import api
from app import config_db
from app.config_loader import CentralConfig, ensure_dirs, load_config
from app.db import datenbank as db
from app.indexer.index_lauf_service import (
    run_index_lauf,
    stop_event,
    load_run_id,
    get_live_status,
    get_log_tail,
    get_log_since,
)
from app import metrics

logging.basicConfig(level=logging.INFO)
index_lock = threading.Lock()
_metrics_thread_started = False
_metrics_thread_lock = threading.Lock()


def get_config() -> CentralConfig:
    return load_config()


def ensure_app_secret(env_path: Path = Path(".env")) -> str:
    env_val = os.getenv("APP_SECRET")
    if env_val:
        return env_val.strip()

    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("APP_SECRET="):
                    value = line.split("=", 1)[1].strip()
                    if value:
                        os.environ["APP_SECRET"] = value
                        return value
        except Exception:
            pass

    secret = secrets.token_urlsafe(32)
    try:
        existing = env_path.exists() and env_path.stat().st_size > 0
        with env_path.open("a", encoding="utf-8") as f:
            if existing:
                f.write("\n")
            f.write(f"APP_SECRET={secret}\n")
    except Exception:
        pass
    os.environ["APP_SECRET"] = secret
    return secret


def get_test_flags(request: Request) -> tuple[bool, Optional[str]]:
    params = request.query_params
    is_test = params.get("metrics_test") == "1" or request.headers.get("X-Metrics-Test") == "1"
    test_run_id = params.get("test_run_id") or request.headers.get("X-Test-Run-Id")
    return is_test, test_run_id


def ensure_metrics_background() -> None:
    global _metrics_thread_started
    with _metrics_thread_lock:
        if _metrics_thread_started:
            return
        _metrics_thread_started = True

    def worker():
        while True:
            try:
                metrics.record_system_slot()
            except Exception:
                pass
            time.sleep(60)

    threading.Thread(target=worker, daemon=True).start()


def require_secret(
    request: Request,
    x_app_secret: Optional[str] = Header(default=None, alias="X-App-Secret"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    app_secret_cookie: Optional[str] = Cookie(default=None, alias="app_secret"),
    x_internal_auth: Optional[str] = Header(default=None, alias="X-Internal-Auth"),
):
    if x_internal_auth and x_internal_auth.strip() == "1":
        return True

    expected = ensure_app_secret()
    supplied = None
    if x_app_secret:
        supplied = x_app_secret.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    elif app_secret_cookie:
        supplied = app_secret_cookie.strip()

    if not supplied or supplied != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


def read_version() -> str:
    candidates = [
        Path(__file__).resolve().parent.parent / "VERSION",
        Path.cwd() / "VERSION",
    ]
    for path in candidates:
        try:
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    return content
        except Exception:
            continue
    return "v?"


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
    ensure_app_secret()
    ensure_dirs(config)
    db.init_db()
    metrics.init_metrics()
    ensure_metrics_background()

    MAX_SEARCH_LIMIT = 500
    MIN_QUERY_LENGTH = 2

    app = FastAPI(title="Index-Suche")
    templates = Jinja2Templates(directory="app/frontend/templates")
    app.mount("/static", StaticFiles(directory="app/frontend/static"), name="static")
    LOG_PAGE_SIZE = 200

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "default_preview": config.ui.default_preview,
                "snippet_length": config.ui.snippet_length,
                "app_version": read_version(),
            },
        )

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        return templates.TemplateResponse("dashboard.html", {"request": request, "app_version": read_version()})

    @app.get("/viewer", response_class=HTMLResponse)
    def viewer(request: Request, id: int = Query(...)):
        return templates.TemplateResponse(
            "viewer.html",
            {
                "request": request,
                "doc_id": id,
                "app_version": read_version(),
            },
        )

    @app.get("/metrics", response_class=HTMLResponse)
    def metrics_page(request: Request):
        return templates.TemplateResponse("metrics.html", {"request": request, "app_version": read_version()})

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
        _auth: bool = Depends(require_secret),
    ):
        raw_q = (q or "").strip()
        if raw_q and len(raw_q) < MIN_QUERY_LENGTH:
            return {"results": [], "has_more": False, "message": f"Suchbegriff zu kurz (min. {MIN_QUERY_LENGTH} Zeichen)"}

        safe_limit = max(1, min(MAX_SEARCH_LIMIT, int(limit or 0)))
        safe_offset = max(0, int(offset or 0))

        db.init_db()
        with db.get_conn() as conn:
            filters = {}
            if source:
                filters["source"] = source
            if extension:
                filters["extension"] = extension.lower()
            if time_filter:
                filters["time_filter"] = time_filter
            fetch_limit = safe_limit + 1  # eine mehr holen, um has_more zu erkennen
            rows = db.search_documents(
                conn,
                build_match_query(q),
                limit=fetch_limit,
                offset=safe_offset,
                filters=filters,
                sort_key=sort_key,
                sort_dir=sort_dir,
            )
            has_more = len(rows) > safe_limit
            rows = rows[:safe_limit]
            return {"results": [dict(row) for row in rows], "has_more": has_more}

    @app.get("/api/document/{doc_id}")
    def document_details(doc_id: int, request: Request, _auth: bool = Depends(require_secret)):
        t_start = time.perf_counter()
        is_test, test_run_id = get_test_flags(request)
        with db.get_conn() as conn:
            row = db.get_document(conn, doc_id)
            if not row:
                raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
            content = db.get_document_content(conn, doc_id)
        data = dict(row)
        data["content"] = content
        try:
            metrics.record_event(
                {
                    "endpoint": "document_meta",
                    "doc_id": doc_id,
                    "path": data.get("path"),
                    "source": data.get("source"),
                    "size_bytes": data.get("size_bytes"),
                    "extension": data.get("extension"),
                    "server_total_ms": (time.perf_counter() - t_start) * 1000,
                    "status_code": 200,
                    "is_test": is_test,
                    "test_run_id": test_run_id,
                    "user_agent": request.headers.get("User-Agent"),
                }
            )
        except Exception:
            pass
        return data

    @app.get("/api/document/{doc_id}/file")
    def document_file(
        doc_id: int,
        request: Request,
        download: bool = Query(False, description="Download erzwingen"),
        _auth: bool = Depends(require_secret),
    ):
        is_test, test_run_id = get_test_flags(request)
        t_start = time.perf_counter()
        with db.get_conn() as conn:
            row = db.get_document(conn, doc_id)
        if not row:
            raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
        row_dict = dict(row)
        path = Path(row_dict["path"])
        if not path.exists():
            try:
                metrics.record_event(
                    {
                        "endpoint": "document_file",
                        "doc_id": doc_id,
                        "path": str(path),
                        "source": row_dict.get("source"),
                        "size_bytes": row_dict.get("size_bytes"),
                        "extension": row_dict.get("extension"),
                        "server_total_ms": (time.perf_counter() - t_start) * 1000,
                        "status_code": 404,
                        "is_test": is_test,
                        "test_run_id": test_run_id,
                        "user_agent": request.headers.get("User-Agent"),
                    }
                )
            except Exception:
                pass
            raise HTTPException(status_code=404, detail="Datei nicht mehr vorhanden")

        media_type, _ = mimetypes.guess_type(path.name)
        disposition = "attachment" if download else "inline"
        headers = {"Content-Disposition": f'{disposition}; filename="{path.name}"'}

        stat_start = time.perf_counter()
        stat_ms = 0.0
        file_size = row_dict.get("size_bytes")
        try:
            st = path.stat()
            file_size = file_size or getattr(st, "st_size", None)
            stat_ms = (time.perf_counter() - stat_start) * 1000
        except Exception:
            stat_ms = (time.perf_counter() - stat_start) * 1000
        if file_size:
            headers["Content-Length"] = str(file_size)

        open_start = time.perf_counter()
        f = path.open("rb")
        open_ms = (time.perf_counter() - open_start) * 1000

        chunk_size = 64 * 1024
        first_read_start = time.perf_counter()
        first_chunk = f.read(chunk_size)
        first_read_ms = (time.perf_counter() - first_read_start) * 1000
        ttfb_ms = (time.perf_counter() - t_start) * 1000
        transfer_start = time.perf_counter()
        bytes_sent = 0

        def file_iter():
            nonlocal bytes_sent
            try:
                if first_chunk:
                    bytes_sent += len(first_chunk)
                    yield first_chunk
                for chunk in iter(lambda: f.read(chunk_size), b""):
                    bytes_sent += len(chunk)
                    yield chunk
            finally:
                f.close()
                end_time = time.perf_counter()
                transfer_ms = (end_time - transfer_start) * 1000
                total_ms = (end_time - t_start) * 1000
                try:
                    metrics.record_event(
                        {
                            "endpoint": "document_file",
                            "doc_id": doc_id,
                            "path": str(path),
                            "source": row_dict.get("source"),
                            "size_bytes": row_dict.get("size_bytes"),
                            "extension": row_dict.get("extension"),
                            "server_ttfb_ms": ttfb_ms,
                            "server_total_ms": total_ms,
                            "smb_first_read_ms": first_read_ms + open_ms + stat_ms,
                            "transfer_ms": transfer_ms,
                            "bytes_sent": bytes_sent,
                            "status_code": 200,
                            "is_test": is_test,
                            "test_run_id": test_run_id,
                            "user_agent": request.headers.get("User-Agent"),
                        }
                    )
                except Exception:
                    pass

        return StreamingResponse(file_iter(), media_type=media_type, headers=headers)

    @app.get("/api/admin/status")
    def admin_status(_auth: bool = Depends(require_secret)):
        db.init_db()
        with db.get_conn() as conn:
            status = db.get_status(conn)
            ext_counts = [
                {"extension": row["extension"], "count": row["c"]}
                for row in status["ext_counts"]
            ]
            recent_runs = [dict(r) for r in status["recent_runs"]]
            last_run = dict(status["last_run"]) if status["last_run"] else None
            return {
                "total_docs": int(status["total_docs"]),
                "ext_counts": ext_counts,
                "last_run": last_run,
                "recent_runs": recent_runs,
                "errors_total": db.error_count(conn),
                "send_report_enabled": config_db.get_setting("send_report_enabled", "0") == "1",
            }

    @app.get("/api/admin/roots")
    def admin_roots(_auth: bool = Depends(require_secret)):
        roots = [
            {"id": rid, "path": path, "label": label, "active": active}
            for path, label, rid, active in config_db.list_roots(active_only=False)
        ]
        return {"roots": roots, "base_data_root": config_db.get_setting("base_data_root", "/data")}

    @app.post("/api/admin/roots")
    def add_root(path: str = Query(...), label: Optional[str] = Query(None), active: bool = Query(True), _auth: bool = Depends(require_secret)):
        base = config_db.get_setting("base_data_root", "/data")
        if base and not str(path).startswith(base):
            raise HTTPException(status_code=400, detail=f"Pfad muss unter {base} liegen")
        rid = config_db.add_root(path, label, active)
        return {"id": rid}

    @app.delete("/api/admin/roots/{root_id}")
    def delete_root(root_id: int, _auth: bool = Depends(require_secret)):
        config_db.delete_root(root_id)
        return {"status": "ok"}

    @app.post("/api/admin/roots/{root_id}/activate")
    def activate_root(root_id: int, active: bool = Query(True), _auth: bool = Depends(require_secret)):
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
    def trigger_index(full_reset: bool = Query(False), _auth: bool = Depends(require_secret)):
        status = _start_index(full_reset)
        if status == "busy":
            return JSONResponse({"status": "busy"}, status_code=409)
        return {"status": status}

    @app.post("/api/admin/index/reset")
    def reset_index(_auth: bool = Depends(require_secret)):
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

    @app.post("/api/admin/index/reset_run")
    def reset_and_run(_auth: bool = Depends(require_secret)):
        if not index_lock.acquire(blocking=False):
            return JSONResponse({"status": "busy"}, status_code=409)
        def runner():
            try:
                for suffix in ["data/index.db", "data/index.db-wal", "data/index.db-shm"]:
                    p = Path(suffix)
                    if p.exists():
                        p.unlink()
                db.init_db()
                cfg = load_config()
                run_index_lauf(cfg)
            finally:
                index_lock.release()
        threading.Thread(target=runner, daemon=True).start()
        return {"status": "started_after_reset"}

    @app.post("/api/admin/index/stop")
    def stop_index(_auth: bool = Depends(require_secret)):
        stop_event.set()
        # writer will flush and status will be "stopped"
        return {"status": "stopping"}

    def get_send_report_enabled() -> bool:
        env_val = os.getenv("SEND_REPORT_ENABLED")
        if env_val is not None:
            return env_val.strip() == "1"
        try:
            val = config_db.get_setting("send_report_enabled", "0")
            return val == "1"
        except Exception:
            return False

    @app.get("/api/admin/preflight")
    def preflight(_auth: bool = Depends(require_secret)):
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
    def admin_errors(limit: int = 50, offset: int = 0, _auth: bool = Depends(require_secret)):
        db.init_db()
        with db.get_conn() as conn:
            rows = db.list_errors(conn, limit=limit, offset=offset)
            total = db.error_count(conn)
            return {"errors": [dict(r) for r in rows], "total": total}

    @app.post("/api/admin/reporting/send_report")
    def toggle_send_report(enabled: bool = Query(...), _auth: bool = Depends(require_secret)):
        try:
            config_db.set_setting("send_report_enabled", "1" if enabled else "0")
        except Exception:
            pass
        return {"enabled": enabled}

    @app.get("/api/admin/indexer_log")
    def admin_indexer_log(
        offset: int = 0,
        limit: int = LOG_PAGE_SIZE,
        since: Optional[int] = Query(None, description="Zeilennummer/Seq, ab der gelesen wird"),
        tail: Optional[int] = Query(None, description="Letzte N Zeilen zurückgeben"),
        _auth: bool = Depends(require_secret),
    ):
        """
        Liefert das Indexer-Log aus dem Live-Puffer (neuestes zuletzt).
        """
        try:
            if since is not None:
                data = get_log_since(int(since), limit or LOG_PAGE_SIZE)
            else:
                tail_value = tail if tail is not None else (limit or LOG_PAGE_SIZE)
                data = get_log_tail(tail_value)
            return {
                "lines": data["lines"],
                "has_more_newer": False,
                "has_more_older": False,
                "total": data["total"],
                "from": data["from"],
            }
        except Exception:
            return {"lines": [], "has_more_newer": False, "has_more_older": False, "total": 0, "from": 0}

    @app.get("/api/admin/indexer_status")
    def admin_indexer_status(_auth: bool = Depends(require_secret)):
        live = get_live_status()
        run_id = live.get("run_id") if live else load_run_id()
        heartbeat_ts = live.get("heartbeat") if live else None
        hb_path = Path("data/index.heartbeat")
        if heartbeat_ts is None and hb_path.exists():
            try:
                heartbeat_ts = int(hb_path.read_text().strip())
            except Exception:
                heartbeat_ts = None
        heartbeat_age = None
        if heartbeat_ts:
            heartbeat_age = max(0, int(time.time()) - int(heartbeat_ts))
        db.init_db()
        last_run = None
        with db.get_conn() as conn:
            row = db.get_last_run(conn)
            if row:
                last_run = dict(row)
        return {
            "run_id": run_id,
            "heartbeat": heartbeat_ts,
            "heartbeat_age": heartbeat_age,
            "last_run": last_run,
            "version": read_version(),
            "live": live,
        }

    @app.get("/api/admin/metrics/summary")
    def admin_metrics_summary(
        window_seconds: int = Query(24 * 3600, ge=60, le=14 * 24 * 3600),
        endpoint: Optional[str] = Query(None),
        extension: Optional[str] = Query(None),
        is_test: Optional[bool] = Query(None),
        _auth: bool = Depends(require_secret),
    ):
        return metrics.get_summary(
            window_seconds=window_seconds,
            endpoint=endpoint,
            extension=extension,
            is_test=is_test,
        )

    @app.get("/api/admin/metrics/events")
    def admin_metrics_events(limit: int = Query(200, ge=1, le=1000), is_test: Optional[bool] = Query(None), _auth: bool = Depends(require_secret)):
        return {"events": metrics.get_recent_events(limit=limit, is_test=is_test)}

    @app.get("/api/admin/metrics/system")
    def admin_metrics_system(limit: int = Query(240, ge=1, le=1440), _auth: bool = Depends(require_secret)):
        return {"slots": metrics.get_system_slots(limit=limit)}

    @app.post("/api/admin/metrics/client_event")
    async def admin_metrics_client_event(payload: Dict[str, Any], request: Request, _auth: bool = Depends(require_secret)):
        is_test, test_run_id = get_test_flags(request)
        event = {
            "endpoint": "client_preview",
            "doc_id": payload.get("doc_id"),
            "size_bytes": payload.get("size_bytes"),
            "extension": payload.get("extension"),
            "client_click_ts": payload.get("client_click_ts"),
            "client_resp_start_ts": payload.get("client_resp_start_ts"),
            "client_resp_end_ts": payload.get("client_resp_end_ts"),
            "client_render_end_ts": payload.get("client_render_end_ts"),
            "is_test": is_test or payload.get("is_test"),
            "test_run_id": payload.get("test_run_id") or test_run_id,
            "user_agent": request.headers.get("User-Agent"),
            "status_code": payload.get("status_code") or 200,
        }
        try:
            metrics.record_event(event)
        except Exception:
            pass
        return {"status": "ok"}

    def list_children(path: Path) -> list:
        try:
            return [
                {"name": entry.name, "path": str(entry), "has_children": any(child.is_dir() for child in entry.iterdir())}
                for entry in sorted([e for e in path.iterdir() if e.is_dir()])
            ]
        except Exception:
            return []

    @app.get("/api/admin/tree")
    def admin_tree(parent: Optional[str] = Query(None), _auth: bool = Depends(require_secret)):
        base_root = Path(config_db.get_setting("base_data_root", "/data"))
        if not base_root.exists():
            return {"base": str(base_root), "children": []}
        target = Path(parent) if parent else base_root
        return {"base": str(base_root), "parent": str(target), "children": list_children(target)}

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
