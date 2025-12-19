import os
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


def _slugify(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name)
    return safe[:80] or "test"


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


@pytest.fixture(scope="session")
def artifacts_dir():
    root = Path(os.getenv("E2E_ARTIFACT_DIR", "test-artifacts")) / time.strftime("%Y%m%d-%H%M%S")
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(scope="session")
def base_url():
    return os.getenv("APP_BASE_URL", "http://localhost:8010")


@pytest.fixture(scope="session")
def app_secret():
    return os.getenv("APP_SECRET", "")


@pytest.fixture(scope="session")
def admin_password():
    return os.getenv("ADMIN_PASSWORD", "admin")


@pytest.fixture
def page(request, artifacts_dir, base_url, app_secret):
    headless_env = os.getenv("HEADFUL", "").lower()
    headless = headless_env not in {"1", "true", "yes", "on"}
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context()
    if app_secret:
        context.add_cookies([{"name": "app_secret", "value": app_secret, "url": f"{base_url}/"}])
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    page.set_default_timeout(15000)

    yield page

    test_dir = artifacts_dir / _slugify(request.node.name)
    test_dir.mkdir(parents=True, exist_ok=True)
    rep_call = getattr(request.node, "rep_call", None)
    failed = bool(rep_call and getattr(rep_call, "failed", False))
    trace_path = test_dir / "trace.zip"
    try:
        if failed:
            context.tracing.stop(path=trace_path)
        else:
            context.tracing.stop()
    except Exception:
        pass
    if failed:
        screenshot_path = test_dir / "failure.png"
        try:
            page.screenshot(path=screenshot_path, full_page=True)
        except Exception:
            pass

    browser.close()
    playwright.stop()
