import pytest


def read_zoom_state(page):
    return page.evaluate(
        "() => {"
        "  const doc = document.documentElement;"
        "  const csHtml = getComputedStyle(doc);"
        "  const csBody = getComputedStyle(document.body);"
        "  const parse = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : null; };"
        "  return {"
        "    htmlZoom: parse(csHtml.zoom),"
        "    bodyZoom: parse(csBody.zoom)"
        "  };"
        "}"
    )


@pytest.mark.e2e
@pytest.mark.critical
def test_zoom_stays_consistent_across_pages_and_preview(page, base_url):
    states = []

    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=20000)
    page.wait_for_selector("#search-input", timeout=5000)
    states.append(("index", read_zoom_state(page)))

    page.fill("#search-input", "zebra")
    page.wait_for_timeout(800)
    page.wait_for_selector("#results-table tbody tr", timeout=7000)
    states.append(("after_search", read_zoom_state(page)))

    page.click("#results-table tbody tr")
    page.wait_for_selector("#preview-panel:not(.hidden)", timeout=8000)
    states.append(("preview_panel", read_zoom_state(page)))

    page.goto(f"{base_url}/dashboard", wait_until="domcontentloaded", timeout=15000)
    states.append(("dashboard", read_zoom_state(page)))

    page.goto(f"{base_url}/metrics", wait_until="domcontentloaded", timeout=15000)
    states.append(("metrics", read_zoom_state(page)))

    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=15000)
    states.append(("back_to_index", read_zoom_state(page)))

    base = states[0][1]
    base_body = base["bodyZoom"] or 1
    base_html = base["htmlZoom"] or 1
    for label, state in states[1:]:
        body = state["bodyZoom"] or 1
        html = state["htmlZoom"] or 1
        assert body == pytest.approx(base_body, rel=1e-3), f"body zoom drift at {label}"
        assert html == pytest.approx(base_html, rel=1e-3), f"html zoom drift at {label}"
