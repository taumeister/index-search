import hashlib
import hmac
import logging
import secrets
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

import uvicorn
from fastapi import Cookie, Depends, FastAPI, HTTPException, Header, Query, Request, Response
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
    stop_event,
    load_run_id,
    get_live_status,
    get_log_tail,
    get_log_since,
)
from app import metrics
from app.search_modes import SearchMode, build_search_plan, normalize_mode
from app import config_db
from app.feedback import MAX_FEEDBACK_CHARS, check_rate_limit, send_feedback_email
from app.index_runner import start_index_run
from app.auto_index_scheduler import AutoIndexScheduler, AutoIndexConfig, load_config_from_db, load_status_from_db, persist_config
from app.services import file_ops

logging.basicConfig(level=logging.INFO)
_metrics_thread_started = False
_metrics_thread_lock = threading.Lock()
logger = logging.getLogger(__name__)
_auto_scheduler: Optional[AutoIndexScheduler] = None
ADMIN_SESSION_COOKIE = "admin_session"
ADMIN_SESSION_TTL_SEC = 12 * 3600


def get_config() -> CentralConfig:
    return load_config()


def resolve_active_roots(config: CentralConfig) -> list[tuple[Path, str]]:
    """
    Liefert aktive Roots aus der Config-DB, andernfalls die env/INI-Roots.
    Validiert Basis-Pfad und Existenz, fällt aber nicht stillschweigend auf /data zurück.
    """
    db_roots = config_db.list_roots(active_only=True)
    if db_roots:
        base_root = Path(config_db.get_setting("base_data_root", "/data")).resolve()
        if not base_root.exists():
            raise ValueError(f"Basis-Ordner nicht gefunden: {base_root}")
        resolved: list[tuple[Path, str]] = []
        for path, label, _rid, _active in db_roots:
            p = Path(path).resolve()
            if not p.is_dir():
                raise ValueError(f"Wurzelpfad nicht gefunden: {p}")
            try:
                p.relative_to(base_root)
            except ValueError:
                raise ValueError(f"Pfad {p} liegt nicht unter Basis {base_root}")
            resolved.append((p, label or p.name))
        return resolved

    # Fallback: env/INI-Roots
    if config.paths.roots:
        return config.paths.roots

    raise ValueError("Keine aktiven Quellen konfiguriert")


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


def get_admin_password(env_path: Path = Path(".env")) -> str:
    value = os.getenv("ADMIN_PASSWORD")
    if value and value.strip():
        return value.strip()
    try:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("ADMIN_PASSWORD="):
                    candidate = line.split("=", 1)[1].strip()
                    if candidate:
                        os.environ["ADMIN_PASSWORD"] = candidate
                        return candidate
    except Exception:
        pass
    raise ValueError("ADMIN_PASSWORD muss gesetzt sein")


def _admin_token_secret() -> str:
    return f"{ensure_app_secret()}::{get_admin_password()}"


def issue_admin_token() -> str:
    issued = int(time.time())
    nonce = secrets.token_hex(8)
    payload = f"{issued}:{nonce}"
    secret = _admin_token_secret().encode("utf-8")
    sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_admin_token(token: Optional[str]) -> bool:
    if not token:
        return False
    try:
        payload, sig = token.split(".", 1)
    except ValueError:
        return False
    secret = _admin_token_secret().encode("utf-8")
    expected = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False
    ts_part = payload.split(":", 1)[0]
    try:
        issued = int(ts_part)
    except ValueError:
        return False
    if issued + ADMIN_SESSION_TTL_SEC < time.time():
        return False
    return True


def is_admin(request: Request) -> bool:
    token = request.cookies.get(ADMIN_SESSION_COOKIE)
    return verify_admin_token(token)


def init_quarantine_state(config: CentralConfig) -> None:
    try:
        roots = resolve_active_roots(config)
    except Exception as exc:
        try:
            roots = getattr(config.paths, "roots", [])
        except Exception:
            roots = []
        logger.warning("Quarantäne-Setup übersprungen: %s", exc)
    file_ops.init_sources(roots)


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


def require_admin(request: Request, _auth: bool = Depends(require_secret)):
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin erforderlich")
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


def create_app(config: Optional[CentralConfig] = None) -> FastAPI:
    config = config or load_config()
    get_admin_password()
    ensure_app_secret()
    ensure_dirs(config)
    init_quarantine_state(config)
    db.init_db()
    metrics.init_metrics()
    ensure_metrics_background()
    global _auto_scheduler
    if not os.getenv("AUTO_INDEX_DISABLE", "").lower() == "1" and not os.getenv("PYTEST_CURRENT_TEST"):
        _auto_scheduler = AutoIndexScheduler(
            lambda **kwargs: start_index_run(resolve_roots=resolve_active_roots, **kwargs)
        )
        _auto_scheduler.start()
    feedback_enabled = bool(getattr(config, "feedback", None) and config.feedback.enabled)
    feedback_recipients = list(getattr(config.feedback, "recipients", []))
    app_version = read_version()

    MAX_SEARCH_LIMIT = 500
    MIN_QUERY_LENGTH = 2
    DEFAULT_SEARCH_MODE = normalize_mode(getattr(config.ui, "search_default_mode", None), SearchMode.STANDARD)
    PREFIX_MINLEN = max(1, int(getattr(config.ui, "search_prefix_minlen", 4) or 4))

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
                "app_version": app_version,
                "search_default_mode": getattr(config.ui, "search_default_mode", "standard"),
                "search_prefix_minlen": getattr(config.ui, "search_prefix_minlen", 4),
                "feedback_enabled": feedback_enabled,
            },
        )

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        return templates.TemplateResponse("dashboard.html", {"request": request, "app_version": app_version})

    @app.get("/viewer", response_class=HTMLResponse)
    def viewer(request: Request, id: int = Query(...)):
        return templates.TemplateResponse(
            "viewer.html",
            {
                "request": request,
                "doc_id": id,
                "app_version": app_version,
            },
        )

    @app.get("/metrics", response_class=HTMLResponse)
    def metrics_page(request: Request):
        return templates.TemplateResponse("metrics.html", {"request": request, "app_version": app_version})

    def serialize_status(st: Any) -> Dict[str, Any]:
        return {
            "last_run_at": st.last_run_at.isoformat() if getattr(st, "last_run_at", None) else None,
            "last_duration_sec": st.last_duration_sec,
            "last_status": st.last_status,
            "last_error": st.last_error,
            "next_run_at": st.next_run_at.isoformat() if getattr(st, "next_run_at", None) else None,
            "running": bool(getattr(st, "running", False)),
        }

    def serialize_config(cfg: AutoIndexConfig) -> Dict[str, Any]:
        return {
            "enabled": cfg.enabled,
            "mode": cfg.mode,
            "time": cfg.time,
            "weekday": cfg.weekday,
            "interval_hours": cfg.interval_hours,
        }

    @app.get("/api/auto-index/config")
    def auto_index_get_config(_auth: bool = Depends(require_secret)):
        cfg = load_config_from_db()
        st = _auto_scheduler.status() if _auto_scheduler else load_status_from_db()
        return {"config": serialize_config(cfg), "status": serialize_status(st)}

    @app.post("/api/auto-index/config")
    async def auto_index_set_config(payload: Dict[str, Any], _auth: bool = Depends(require_secret)):
        mode = (payload.get("mode") or "daily").strip().lower()
        if mode not in {"daily", "weekly", "interval"}:
            raise HTTPException(status_code=400, detail="Ungültiger Modus")
        enabled = bool(payload.get("enabled", False))
        time_str = payload.get("time") or "02:00"
        weekday = int(payload.get("weekday") or 0)
        interval_hours = int(payload.get("interval_hours") or 6)
        cfg = AutoIndexConfig(
            enabled=enabled,
            mode=mode,
            time=time_str,
            weekday=weekday,
            interval_hours=interval_hours,
        )
        persist_config(cfg)
        if _auto_scheduler:
            _auto_scheduler.update_config(cfg)
            st = _auto_scheduler.status()
        else:
            st = load_status_from_db()
        return {"config": serialize_config(cfg), "status": serialize_status(st)}

    @app.post("/api/auto-index/run")
    def auto_index_run(_auth: bool = Depends(require_secret)):
        if _auto_scheduler:
            res = _auto_scheduler.trigger_now()
        else:
            res = start_index_run(resolve_roots=resolve_active_roots)
        if res == "busy":
            raise HTTPException(status_code=409, detail="Lauf läuft bereits")
        return {"status": res}

    @app.get("/api/auto-index/status")
    def auto_index_status(_auth: bool = Depends(require_secret)):
        st = _auto_scheduler.status() if _auto_scheduler else load_status_from_db()
        return {"status": serialize_status(st)}

    @app.post("/api/feedback")
    async def submit_feedback(payload: Dict[str, Any], request: Request, _auth: bool = Depends(require_secret)):
        if not feedback_enabled:
            raise HTTPException(status_code=403, detail="Feedback deaktiviert")
        if not config.smtp:
            raise HTTPException(status_code=503, detail="E-Mail-Versand nicht verfügbar")
        if not feedback_recipients:
            raise HTTPException(status_code=503, detail="Feedback-Ziel nicht konfiguriert")

        client_id = request.client.host if request.client else "unknown"
        if not check_rate_limit(client_id):
            raise HTTPException(status_code=429, detail="Zu viele Feedbacks. Bitte später erneut versuchen.")

        message_html = ""
        message_text = ""
        try:
            message_html = (payload.get("message_html") or "")[: MAX_FEEDBACK_CHARS * 4]
            message_text = (payload.get("message_text") or "")[: MAX_FEEDBACK_CHARS * 2]
        except Exception:
            pass

        try:
            send_feedback_email(config, feedback_recipients, message_html, message_text, app_version)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.error("Feedback-Versand fehlgeschlagen: %s", exc)
            raise HTTPException(status_code=500, detail="Versand fehlgeschlagen")

        return {"status": "ok"}

    @app.get("/api/search")
    def search(
        q: str = Query("", description="Suchbegriff"),
        source: Optional[str] = None,
        source_labels: Optional[list[str]] = Query(None, alias="source_labels"),
        extension: Optional[str] = None,
        time_filter: Optional[str] = None,
        sort_key: Optional[str] = None,
        sort_dir: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
        mode: Optional[str] = Query(None, description="Suchmodus (strict|standard|loose)"),
        _auth: bool = Depends(require_secret),
    ):
        safe_limit = max(1, min(MAX_SEARCH_LIMIT, int(limit or 0)))
        safe_offset = max(0, int(offset or 0))

        db.init_db()
        with db.get_conn() as conn:
            filters = {}
            label_filter = [s.strip() for s in (source_labels or []) if s and s.strip()]
            if source and not label_filter:
                label_filter = [source]
            if label_filter:
                filters["source_labels"] = label_filter
            if extension:
                filters["extension"] = extension.lower()
            if time_filter:
                filters["time_filter"] = time_filter

            raw_q = (q or "").strip()
            if raw_q and raw_q != "*" and len(raw_q) < MIN_QUERY_LENGTH:
                return {"results": [], "has_more": False, "message": f"Suchbegriff zu kurz (min. {MIN_QUERY_LENGTH} Zeichen)"}

            effective_mode = normalize_mode(mode, DEFAULT_SEARCH_MODE)
            plan = build_search_plan(raw_q, effective_mode, PREFIX_MINLEN, allow_wildcard=bool(filters))
            if plan.empty_reason:
                return {"results": [], "has_more": False, "message": plan.empty_reason}

            fetch_limit = safe_limit + 1  # eine mehr holen, um has_more zu erkennen
            rows = db.search_documents(
                conn,
                plan.fts_query or "",
                limit=fetch_limit,
                offset=safe_offset,
                filters=filters,
                sort_key=sort_key,
                sort_dir=sort_dir,
            )
            has_more = len(rows) > safe_limit
            rows = rows[:safe_limit]
            return {
                "results": [dict(row) for row in rows],
                "has_more": has_more,
                "mode": effective_mode.value,
            }

    @app.get("/api/sources")
    def list_sources(_auth: bool = Depends(require_secret)):
        labels: list[str] = []
        try:
            labels = [label for _, label in resolve_active_roots(config)]
        except Exception:
            try:
                labels = [label for _, label in getattr(config.paths, "roots", [])]
            except Exception:
                labels = []
        cleaned = sorted({(lbl or "").strip() for lbl in labels if (lbl or "").strip()})
        return {"labels": cleaned}

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
    @app.get("/api/document/{doc_id}/file/{filename}")
    def document_file(
        doc_id: int,
        request: Request,
        download: bool = Query(False, description="Download erzwingen"),
        filename: Optional[str] = None,
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

    @app.post("/api/files/{doc_id}/quarantine-delete")
    def quarantine_delete(doc_id: int, request: Request, _admin: bool = Depends(require_admin)):
        file_ops.refresh_quarantine_state()
        try:
            result = file_ops.quarantine_delete(doc_id, actor="admin")
        except file_ops.FileOpError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        except Exception as exc:
            logger.error("Quarantäne-Verschiebung fehlgeschlagen: %s", exc)
            raise HTTPException(status_code=500, detail="Quarantäne fehlgeschlagen")
        return {"status": "ok", **result}

    @app.get("/api/admin/status")
    def admin_status(request: Request, _auth: bool = Depends(require_secret)):
        db.init_db()
        file_ops.refresh_quarantine_state()
        ops_state = file_ops.get_status()
        admin_flag = is_admin(request)
        with db.get_conn() as conn:
            status = db.get_status(conn)
            ext_counts = [
                {"extension": row["extension"], "count": row["c"]}
                for row in status["ext_counts"]
            ]
            recent_runs = [dict(r) for r in status["recent_runs"]]
            last_run = dict(status["last_run"]) if status["last_run"] else None
            return {
                "admin": admin_flag,
                "file_ops_enabled": ops_state["file_ops_enabled"],
                "quarantine_ready_sources": ops_state["quarantine_ready_sources"],
                "index_exclude_dirs": getattr(config.indexer, "exclude_dirs", []),
                "total_docs": int(status["total_docs"]),
                "ext_counts": ext_counts,
                "last_run": last_run,
                "recent_runs": recent_runs,
                "errors_total": db.error_count(conn),
                "send_report_enabled": config_db.get_setting("send_report_enabled", "0") == "1",
            }

    @app.post("/api/admin/login")
    def admin_login(payload: Dict[str, Any], response: Response, _auth: bool = Depends(require_secret)):
        password = (payload.get("password") or "").strip()
        if not secrets.compare_digest(password, get_admin_password()):
            raise HTTPException(status_code=401, detail="Ungültiges Passwort")
        token = issue_admin_token()
        response.set_cookie(
            ADMIN_SESSION_COOKIE,
            token,
            max_age=ADMIN_SESSION_TTL_SEC,
            httponly=True,
            samesite="lax",
            path="/",
        )
        file_ops.refresh_quarantine_state()
        ops_state = file_ops.get_status()
        return {"admin": True, "file_ops_enabled": ops_state["file_ops_enabled"], "quarantine_ready_sources": ops_state["quarantine_ready_sources"]}

    @app.post("/api/admin/logout")
    def admin_logout(response: Response, _auth: bool = Depends(require_secret)):
        response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
        return {"admin": False}

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
        base_path = Path(base).resolve()
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(base_path)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Pfad muss unter {base_path} liegen")
        if not resolved.exists() or not resolved.is_dir():
            raise HTTPException(status_code=400, detail=f"Pfad nicht gefunden: {resolved}")
        rid = config_db.add_root(str(resolved), label, active)
        return {"id": rid}

    @app.delete("/api/admin/roots/{root_id}")
    def delete_root(root_id: int, _auth: bool = Depends(require_secret)):
        config_db.delete_root(root_id)
        return {"status": "ok"}

    @app.post("/api/admin/roots/{root_id}/activate")
    def activate_root(root_id: int, active: bool = Query(True), _auth: bool = Depends(require_secret)):
        config_db.update_root_active(root_id, active)
        return {"status": "ok"}

    @app.post("/api/admin/index/run")
    def trigger_index(full_reset: bool = Query(False), _auth: bool = Depends(require_secret)):
        cfg = load_config()
        try:
            roots = resolve_active_roots(cfg)
        except ValueError as exc:
            return JSONResponse({"status": "error", "detail": str(exc)}, status_code=400)
        status = start_index_run(full_reset, cfg_override=cfg, roots_override=roots, resolve_roots=resolve_active_roots)
        if status == "busy":
            return JSONResponse({"status": "busy"}, status_code=409)
        return {"status": status}

    @app.post("/api/admin/index/reset")
    def reset_index(_auth: bool = Depends(require_secret)):
        status = start_index_run(full_reset=True, reason="reset", resolve_roots=resolve_active_roots)
        if status == "busy":
            return JSONResponse({"status": "busy"}, status_code=409)
        return {"status": status}

    @app.post("/api/admin/index/reset_run")
    def reset_and_run(_auth: bool = Depends(require_secret)):
        status = start_index_run(full_reset=True, reason="reset_run", resolve_roots=resolve_active_roots)
        if status == "busy":
            return JSONResponse({"status": "busy"}, status_code=409)
        return {"status": status}

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
        try:
            roots = resolve_active_roots(cfg)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        exts = {".pdf": 0, ".rtf": 0, ".msg": 0, ".txt": 0}
        for root, _label in roots:
            for dirpath, _, filenames in os.walk(root):
                for name in filenames:
                    s = Path(name).suffix.lower()
                    if s in exts:
                        exts[s] += 1
        return {"counts": exts, "roots": [str(r[0]) for r in roots]}

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
        test_run_id: Optional[str] = Query(None),
        _auth: bool = Depends(require_secret),
    ):
        return metrics.get_summary(
            window_seconds=window_seconds,
            endpoint=endpoint,
            extension=extension,
            is_test=is_test,
            test_run_id=test_run_id,
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

    @app.post("/api/admin/metrics/reset")
    def admin_metrics_reset(_auth: bool = Depends(require_secret)):
        metrics.reset_metrics_storage()
        return {"status": "reset"}

    _metrics_test_lock = threading.Lock()

    @app.post("/api/admin/metrics/test_run")
    def admin_metrics_test_run(
        count: int = Query(200, ge=1, le=1000),
        ext_filter: Optional[str] = Query(None),
        min_size_mb: Optional[float] = Query(0, ge=0),
        _auth: bool = Depends(require_secret),
    ):
        if not _metrics_test_lock.acquire(blocking=False):
            return JSONResponse({"status": "busy"}, status_code=409)
        run_id = f"run-{int(time.time())}"

        def runner():
            try:
                metrics.reset_metrics_storage()
                env = os.environ.copy()
                env["APP_SECRET"] = ensure_app_secret()
                env["METRICS_DOC_LIMIT"] = str(count)
                env["METRICS_BASE_URL"] = "http://localhost:8000"
                env["METRICS_EXT_FILTER"] = (ext_filter or "").strip().lower()
                env["METRICS_MIN_SIZE_MB"] = str(min_size_mb or 0)
                env["METRICS_TEST_RUN_ID"] = run_id
                try:
                    subprocess.run(
                        ["python", "scripts/run_metrics_test.py"],
                        cwd=Path(__file__).resolve().parent.parent,
                        env=env,
                        check=False,
                        timeout=600,
                    )
                except Exception:
                    pass
                try:
                    metrics.save_test_run_artifact(
                        run_id,
                        {
                            "count": count,
                            "ext_filter": ext_filter,
                            "min_size_mb": min_size_mb,
                        },
                    )
                except Exception:
                    pass
            finally:
                _metrics_test_lock.release()

        threading.Thread(target=runner, daemon=True).start()
        return {"status": "started", "count": count, "test_run_id": run_id}

    @app.get("/api/admin/metrics/test_run_results")
    def admin_metrics_test_run_results(
        test_run_id: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=1000),
        _auth: bool = Depends(require_secret),
    ):
        run_id = test_run_id or metrics.get_last_test_run_id()
        if not run_id:
            return {"test_run_id": None, "count": 0, "events": []}
        return metrics.get_test_run_events(run_id, limit=limit)

    @app.get("/api/admin/metrics/runs")
    def admin_metrics_runs(limit: int = Query(20, ge=1, le=100), _auth: bool = Depends(require_secret)):
        return {"runs": metrics.list_run_artifacts(limit=limit)}

    @app.get("/api/admin/metrics/run/{run_id}")
    def admin_metrics_run(run_id: str, _auth: bool = Depends(require_secret)):
        data = metrics.load_run_artifact(run_id)
        if not data:
            raise HTTPException(status_code=404, detail="Run nicht gefunden")
        return data

    @app.get("/api/admin/metrics/run_latest")
    def admin_metrics_run_latest(_auth: bool = Depends(require_secret)):
        run_id = metrics.get_last_test_run_id()
        if not run_id:
            raise HTTPException(status_code=404, detail="Kein Run vorhanden")
        data = metrics.load_run_artifact(run_id)
        if not data:
            raise HTTPException(status_code=404, detail="Run nicht gefunden")
        return data

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
        base_root = Path(config_db.get_setting("base_data_root", "/data")).resolve()
        if not base_root.exists():
            return {"base": str(base_root), "children": []}
        target = Path(parent).resolve() if parent else base_root
        try:
            target.relative_to(base_root)
        except ValueError:
            target = base_root
        return {"base": str(base_root), "parent": str(target), "children": list_children(target)}

    @app.on_event("shutdown")
    def shutdown_scheduler():
        global _auto_scheduler
        if _auto_scheduler:
            try:
                _auto_scheduler.stop()
            except Exception:
                pass

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
