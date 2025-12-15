import os
from urllib.parse import urlparse, parse_qs

import pytest
from playwright.sync_api import sync_playwright, Route


@pytest.mark.e2e
def test_source_filter_adds_params():
    base_url = os.getenv("APP_BASE_URL", "http://localhost:8010")
    secret = os.getenv("APP_SECRET", "")
    search_requests: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        if secret:
            context.add_cookies([{"name": "app_secret", "value": secret, "domain": "localhost", "path": "/"}])

        context.route(
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

        context.route("**/api/search*", handle_search)

        page = context.new_page()
        page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_selector("#source-filter button", timeout=5000)

        page.fill("#search-input", "hello")
        page.wait_for_timeout(600)
        assert search_requests, "Suche sollte ausgelöst werden"

        page.click("button.source-chip:text('Alpha')")
        page.wait_for_timeout(600)
        assert search_requests, "Suche sollte nach Quellen-Filter erneut ausgelöst werden"
        last_params = parse_qs(urlparse(search_requests[-1]).query)
        assert "source_labels" in last_params
        assert "Alpha" in last_params["source_labels"]

        page.click("button.source-chip:text('Beta')")
        page.wait_for_timeout(600)
        last_params = parse_qs(urlparse(search_requests[-1]).query)
        assert set(last_params.get("source_labels", [])) >= {"Alpha", "Beta"}

        browser.close()
