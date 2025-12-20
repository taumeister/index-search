import pytest


PAGES = [
    ("/", {"zen": True, "home": False}),
    ("/dashboard", {"zen": False, "home": True}),
    ("/metrics", {"zen": False, "home": True}),
    ("/docs", {"zen": False, "home": True}),
]


@pytest.mark.e2e
@pytest.mark.smoke
def test_topbar_buttons_per_page(page, base_url):
    for path, expected in PAGES:
        page.goto(f"{base_url}{path}", wait_until="domcontentloaded", timeout=20000)
        assert page.is_visible("#header-menu")
        assert page.is_visible("#theme-toggle-header")
        if expected["home"]:
            assert page.is_visible("#nav-home")
        else:
            assert page.query_selector("#nav-home") is None
        if expected["zen"]:
            assert page.is_visible("#zen-toggle")
        else:
            assert page.query_selector("#zen-toggle") is None


@pytest.mark.e2e
def test_burger_menu_entries_across_pages(page, base_url):
    for path, _expected in PAGES:
        page.goto(f"{base_url}{path}", wait_until="domcontentloaded", timeout=20000)
        page.click("#header-menu", timeout=6000)
        page.wait_for_selector("#header-menu-dropdown:not(.hidden)", timeout=4000)
        for entry in ["#admin-button-menu", "#menu-dashboard", "#menu-metrics", "#menu-docs", "#menu-about"]:
            assert page.is_visible(entry)
        page.click("body")
        page.wait_for_timeout(100)


@pytest.mark.e2e
@pytest.mark.smoke
def test_nav_home_returns_to_index(page, base_url):
    for path in ["/dashboard", "/metrics", "/docs"]:
        page.goto(f"{base_url}{path}", wait_until="domcontentloaded", timeout=20000)
        page.click("#nav-home", timeout=6000)
        page.wait_for_function("() => window.location.pathname === '/'", timeout=12000)


@pytest.mark.e2e
def test_burger_navigation_from_index(page, base_url):
    destinations = [
        ("menu-dashboard", "/dashboard"),
        ("menu-metrics", "/metrics"),
        ("menu-docs", "/docs"),
    ]
    for menu_id, expected_path in destinations:
        page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=20000)
        page.click("#header-menu", timeout=6000)
        page.wait_for_selector("#header-menu-dropdown:not(.hidden)", timeout=4000)
        page.click(f"#{menu_id}", timeout=4000)
        page.wait_for_url(f"{base_url}{expected_path}", timeout=12000)


@pytest.mark.e2e
def test_admin_menu_from_subpage_opens_modal(page, base_url):
    page.goto(f"{base_url}/dashboard", wait_until="domcontentloaded", timeout=20000)
    page.click("#header-menu", timeout=6000)
    page.wait_for_selector("#header-menu-dropdown:not(.hidden)", timeout=4000)
    page.click("#admin-button-menu", timeout=4000)
    page.wait_for_selector("#admin-modal:not(.hidden)", timeout=8000)
    assert page.url.startswith(f"{base_url}/")
