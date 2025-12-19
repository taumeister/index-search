import pytest
from playwright.sync_api import Route


@pytest.mark.e2e
@pytest.mark.critical
def test_feedback_overlay_flow(page, base_url):
    def intercept(route: Route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"status":"ok"}',
        )

    page.context.route("**/api/feedback", intercept)
    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=15000)

    page.evaluate("() => { if (window.openFeedbackOverlay) { window.openFeedbackOverlay(); } }")
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
    count = int(limit_text.split('/')[0].strip())
    assert count >= 12

    page.click("#feedback-send")
    confirm_hidden = page.eval_on_selector("#feedback-confirm", "el => el.classList.contains('hidden')")
    assert confirm_hidden is False

    page.click("#feedback-confirm-yes")
    page.wait_for_timeout(500)
    status_text = page.inner_text("#feedback-status")
    assert "gesendet" in status_text
