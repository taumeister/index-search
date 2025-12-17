import os
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright


def read_zoom_state(page):
    return page.evaluate(
        "() => {"
        "  const doc = document.documentElement;"
        "  const csHtml = getComputedStyle(doc);"
        "  const csBody = getComputedStyle(document.body);"
        "  const parse = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : null; };"
        "  return {"
        "    varZoom: parse(doc.style.getPropertyValue('--app-zoom') || csHtml.getPropertyValue('--app-zoom')),"
        "    htmlZoom: parse(csHtml.zoom),"
        "    bodyZoom: parse(csBody.zoom)"
        "  };"
        "}"
    )


def resolve_base_url():
    base = os.getenv("APP_BASE_URL", "http://localhost:8010")

    def reachable(url: str) -> bool:
        try:
            httpx.get(url, timeout=2, trust_env=False)
            return True
        except Exception:
            return False

    if reachable(base):
        return base
    if "localhost" in base:
        alt = base.replace("localhost", "127.0.0.1")
        if reachable(alt):
            return alt
    pytest.skip("APP_BASE_URL nicht erreichbar")


def resolve_secret():
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("APP_SECRET="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value
    if os.getenv("APP_SECRET"):
        return os.getenv("APP_SECRET")
    return ""


@pytest.mark.e2e
def test_zoom_stays_consistent_across_pages_and_preview():
    base_url = resolve_base_url()
    secret = resolve_secret()
    states = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        if secret:
            context.add_cookies([{"name": "app_secret", "value": secret, "url": f"{base_url}/"}])
        context.add_init_script("window.localStorage.setItem('appZoom','1.6');")

        page = context.new_page()
        page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=15000)
        states.append(("index", read_zoom_state(page)))

        page.click("#type-filter button[data-ext='.pdf']", timeout=4000)
        page.fill("#search-input", "*")
        page.wait_for_timeout(800)
        page.wait_for_selector("#results-table tbody tr:not(.empty-row)", timeout=7000)
        states.append(("after_search", read_zoom_state(page)))

        page.click("#results-table tbody tr:not(.empty-row)")
        page.wait_for_selector("#preview-panel:not(.hidden)", timeout=12000)
        page.wait_for_timeout(400)
        states.append(("preview_panel", read_zoom_state(page)))

        popup_state = None
        try:
            with context.expect_page(timeout=6000) as pop_wait:
                page.click("#open-popup", timeout=3000)
            popup = pop_wait.value
            popup.wait_for_load_state("domcontentloaded", timeout=8000)
            popup_state = read_zoom_state(popup)
            popup.close()
        except Exception:
            popup_state = None

        page.click("a.icon-button[href='/dashboard']", timeout=4000)
        page.wait_for_load_state("domcontentloaded")
        states.append(("dashboard", read_zoom_state(page)))

        page.click("a.icon-button[href='/metrics']", timeout=4000)
        page.wait_for_load_state("domcontentloaded")
        states.append(("metrics", read_zoom_state(page)))

        page.click("a.icon-button[href='/']", timeout=4000)
        page.wait_for_load_state("domcontentloaded")
        states.append(("back_to_index", read_zoom_state(page)))

        page.reload(wait_until="domcontentloaded")
        states.append(("after_reload", read_zoom_state(page)))

        remaining_key = page.evaluate("() => localStorage.getItem('appZoom')")

        browser.close()

    base = states[0][1]
    assert base["bodyZoom"] is not None
    for label, state in states[1:]:
        assert state["bodyZoom"] == pytest.approx(base["bodyZoom"], rel=1e-3), f"body zoom drift at {label}"
        assert state["htmlZoom"] == pytest.approx(base["htmlZoom"], rel=1e-3), f"html zoom drift at {label}"
        assert state["varZoom"] == pytest.approx(base["varZoom"], rel=1e-3), f"css var drift at {label}"

    if popup_state:
        assert popup_state["bodyZoom"] == pytest.approx(base["bodyZoom"], rel=1e-3)
        assert popup_state["varZoom"] == pytest.approx(base["varZoom"], rel=1e-3)

    assert remaining_key is None
