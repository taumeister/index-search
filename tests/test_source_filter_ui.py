import os
from urllib.parse import urlparse, parse_qs

import pytest
from playwright.sync_api import Route


@pytest.mark.e2e
@pytest.mark.smoke
def test_source_filter_adds_params(page, base_url):
    search_requests: list[str] = []

    page.context.route(
        "**/api/sources",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"labels":["Alpha","Beta"]}',
        ),
    )

    def handle_search(route: Route):
        search_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"results":[],"has_more":false}',
        )

    page.context.route("**/api/search*", handle_search)

    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=15000)
    page.wait_for_selector("#source-filter button", timeout=5000)

    page.fill("#search-input", "hello")
    page.wait_for_timeout(700)
    assert search_requests, "Suche sollte ausgelöst werden"

    page.click("button.source-chip:text('Alpha')")
    page.wait_for_timeout(700)
    assert search_requests, "Suche sollte nach Quellen-Filter erneut ausgelöst werden"
    last_params = parse_qs(urlparse(search_requests[-1]).query)
    assert "source_labels" in last_params
    assert "Alpha" in last_params["source_labels"]

    page.click("button.source-chip:text('Beta')")
    page.wait_for_timeout(700)
    last_params = parse_qs(urlparse(search_requests[-1]).query)
    assert set(last_params.get("source_labels", [])) >= {"Alpha", "Beta"}
