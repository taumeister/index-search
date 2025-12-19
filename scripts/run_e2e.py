#!/usr/bin/env python3
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
import socket

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def log(msg: str):
    print(f"[e2e] {msg}")


def copy_testdata(source_root: Path, target_root: Path):
    if target_root.exists():
        shutil.rmtree(target_root)
    shutil.copytree(source_root, target_root)


def wait_for_ready(base_url: str, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{base_url}/", timeout=2.0, trust_env=False)
            if resp.status_code == 200 and "search-input" in resp.text:
                return True
            last_error = f"Status {resp.status_code}"
        except Exception as exc:
            last_error = exc
        time.sleep(1.0)
    if last_error:
        log(f"Ready-Check fehlgeschlagen: {last_error}")
    return False


def prepare_env(args):
    runtime = Path("tmp/e2e-runtime").resolve()
    data_root = runtime / "data"
    config_root = runtime / "config"
    logs_root = runtime / "logs"
    source_root = data_root / "sources" / "demo"
    artifacts_root = Path("test-artifacts") / time.strftime("%Y%m%d-%H%M%S")

    data_root.mkdir(parents=True, exist_ok=True)
    config_root.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)

    if not args.external:
        copy_testdata(Path("testdata/sources/demo"), source_root)

    base_url = args.base_url or f"http://localhost:{args.port}"
    env = os.environ.copy()
    env_updates = {
        "APP_ENV": "test",
        "APP_SECRET": args.app_secret,
        "ADMIN_PASSWORD": args.admin_password,
        "DATA_CONTAINER_PATH": str(data_root),
        "CONFIG_DB_PATH": str(config_root / "config.db"),
        "DB_PATH": str(data_root / "index.db"),
        "METRICS_DB_PATH": str(data_root / "metrics.db"),
        "LOG_DIR": str(logs_root),
        "INDEX_ROOTS": f"{source_root}:{'demo'}",
        "AUTO_INDEX_DISABLE": "1",
        "QUARANTINE_CLEANUP_SCHEDULE": "off",
        "QUARANTINE_AUTO_PURGE": "false",
        "QUARANTINE_CLEANUP_DRYRUN": "true",
        "FEEDBACK_ENABLED": "true",
        "FEEDBACK_TO": "test@example.com",
        "APP_BASE_URL": base_url,
        "E2E_ARTIFACT_DIR": str(artifacts_root),
    }
    if args.external:
        env_updates["E2E_EXTERNAL"] = "1"
    env.update(env_updates)
    os.environ.update(env_updates)
    return env, base_url, runtime, artifacts_root, source_root


def init_config_and_index(source_root: Path, env):
    from app import config_db, index_runner
    from app.config_loader import load_config
    from app.indexer.index_lauf_service import run_index_lauf
    from app.main import resolve_active_roots
    from app.db import datenbank as db

    cfg_path = Path(env["CONFIG_DB_PATH"])
    if cfg_path.exists():
        cfg_path.unlink()
    config_db.CONFIG_DB_PATH = cfg_path
    config_db.ensure_db()
    config_db.set_setting("base_data_root", str(source_root.parent.parent))
    config_db.add_root(str(source_root), "demo", True)

    db_path = Path(env["DB_PATH"])
    if db_path.exists():
        for suffix in ("", "-wal", "-shm"):
            candidate = db_path.with_suffix(db_path.suffix + suffix) if suffix else db_path
            if candidate.exists():
                candidate.unlink()
    index_runner.clear_index_files()
    cfg = load_config()
    cfg.paths.roots = resolve_active_roots(cfg)
    counters = run_index_lauf(cfg)
    log(f"Index gebaut: {counters}")


def start_server(env, port: int, runtime: Path):
    log_path = runtime / "logs" / "uvicorn.log"
    log_file = log_path.open("w", encoding="utf-8")
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
    ]
    proc = subprocess.Popen(cmd, env=env, stdout=log_file, stderr=log_file)
    return proc, log_file


def run_pytest(env, suite: str):
    expr = "e2e and smoke" if suite == "smoke" else "e2e and (smoke or critical)"
    cmd = [sys.executable, "-m", "pytest", "-m", expr]
    log(f"Starte Tests: {' '.join(cmd)}")
    return subprocess.call(cmd, env=env)


def find_free_port(preferred: int) -> int:
    candidates = [preferred] + list(range(preferred + 1, preferred + 10))
    for cand in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", cand))
                return cand
            except OSError:
                continue
    return preferred


def main():
    parser = argparse.ArgumentParser(description="Run E2E/Smoke tests with local server")
    parser.add_argument("--suite", choices=["smoke", "critical"], default="smoke")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--base-url", default=None, help="Override base URL (skip automatic http://localhost:<port> default)")
    parser.add_argument("--app-secret", default="test-secret")
    parser.add_argument("--admin-password", default="admin")
    parser.add_argument("--skip-install", action="store_true", help="Skip playwright install step")
    parser.add_argument("--external", action="store_true", help="Run tests against existing server (no local uvicorn or seeding)")
    args = parser.parse_args()

    if not args.base_url and not args.external:
        chosen = find_free_port(args.port)
        if chosen != args.port:
            log(f"Port {args.port} belegt, weiche auf {chosen} aus")
            args.port = chosen

    env, base_url, runtime, artifacts_root, source_root = prepare_env(args)
    log(f"Nutze Base URL: {base_url}")

    if not args.skip_install:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)

    server = None
    log_file = None
    exit_code = 1
    try:
        if not args.external:
            init_config_and_index(source_root, env)
            server, log_file = start_server(env, args.port, runtime)
            if not wait_for_ready(base_url):
                log("Server wurde nicht bereit innerhalb des Timeouts")
                exit_code = 2
            else:
                log(f"Server bereit unter {base_url}")
        else:
            log("Externer Modus: starte keinen lokalen Server")
            if not wait_for_ready(base_url, timeout=20):
                log(f"Ziel {base_url} nicht erreichbar")
                exit_code = 2
        if exit_code != 2:
            exit_code = run_pytest(env, args.suite)
    finally:
        if server:
            server.send_signal(signal.SIGTERM)
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        if log_file:
            log_file.close()

    if exit_code == 0:
        log("Tests erfolgreich")
    else:
        log(f"Tests fehlgeschlagen, Artefakte unter {artifacts_root}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
