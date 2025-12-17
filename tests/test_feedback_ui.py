import os
import httpx

import pytest
from playwright.sync_api import sync_playwright, Route


@pytest.mark.e2e
def test_feedback_overlay_flow():
    base_url = os.getenv("APP_BASE_URL", "http://localhost:8010")
    try:
        httpx.get(base_url, timeout=2)
    except Exception:
        pytest.skip("APP_BASE_URL nicht erreichbar")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        def intercept(route: Route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"status":"ok"}',
            )

        context.route("**/api/feedback", intercept)
        page = context.new_page()
        page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=15000)

        page.click("#feedback-trigger")
        overlay_hidden = page.eval_on_selector("#feedback-overlay", "el => el.classList.contains('hidden')")
        assert overlay_hidden is False

        page.click("#feedback-editor")
        page.keyboard.type("Test Feedback")
        page.click("button[data-cmd='bold']")
        page.wait_for_function(
            "() => { const t = document.querySelector('#feedback-limit').textContent || ''; const n = parseInt(t, 10); return Number.isFinite(n) && n > 0; }",
            timeout=2000,
        )
        limit_text = page.inner_text("#feedback-limit")
        count = int(limit_text.split("/")[0].strip())
        assert count >= 12

        page.click("#feedback-send")
        confirm_hidden = page.eval_on_selector("#feedback-confirm", "el => el.classList.contains('hidden')")
        assert confirm_hidden is False

        page.click("#feedback-confirm-yes")
        page.wait_for_timeout(500)  # allow fetch handler to resolve
        status_text = page.inner_text("#feedback-status")
        assert "gesendet" in status_text

        browser.close()
