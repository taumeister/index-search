import pytest


@pytest.mark.e2e
@pytest.mark.smoke
def test_search_and_preview_flow(page, base_url):
    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=20000)
    page.wait_for_selector("#search-input", timeout=5000)

    page.fill("#search-input", "zebra")
    page.wait_for_timeout(800)
    page.wait_for_selector("#results-table tbody tr", timeout=7000)
    rows = page.query_selector_all("#results-table tbody tr")
    assert rows, "Es sollten Suchergebnisse angezeigt werden"

    rows[0].click()
    page.wait_for_selector("#preview-panel:not(.hidden)", timeout=8000)
    href = page.get_attribute("#download-link", "href")
    assert href and "/api/document/" in href


@pytest.mark.e2e
@pytest.mark.critical
def test_search_filters_roundtrip(page, base_url):
    seen_params = {}

    def intercept(route):
        url = route.request.url
        from urllib.parse import urlparse, parse_qs

        parsed = parse_qs(urlparse(url).query)
        seen_params.update(parsed)
        route.fulfill(status=200, content_type="application/json", body='{"results":[],"has_more":false}')

    page.context.route("**/api/search*", intercept)
    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=20000)
    page.wait_for_selector("#search-input", timeout=5000)

    page.click("#search-mode button[data-mode='loose']")
    page.click("#type-filter button[data-ext='.txt']")
    page.click("#time-filter-chips button[data-time='last30']")
    page.fill("#search-input", "alpha")
    page.wait_for_timeout(800)
    assert seen_params, "Suchanfrage sollte abgefeuert werden"
    assert seen_params.get("mode", []) == ["loose"]
    assert seen_params.get("extension", []) == [".txt"]
    assert seen_params.get("time_filter", []) == ["last30"]
