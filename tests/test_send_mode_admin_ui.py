import os
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright


def resolve_base_url():
    base = os.getenv("APP_BASE_URL", "http://localhost:8010")

    def reachable(url: str) -> bool:
        try:
            httpx.get(url, timeout=2, follow_redirects=True, trust_env=False)
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


def read_env_value(key: str) -> str:
    val = os.getenv(key, "")
    if val:
        return val
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return ""


def resolve_secret() -> str:
    return read_env_value("APP_SECRET")


def resolve_admin_password() -> str:
    return read_env_value("ADMIN_PASSWORD") or "admin"


def add_secret_cookie(context, base_url: str, secret: str) -> None:
    if not secret:
        return
    context.add_cookies([{"name": "app_secret", "value": secret, "url": f"{base_url}/"}])


def wait_for_modal_open(page):
    page.wait_for_selector("#admin-modal:not(.hidden)", timeout=6000)


@pytest.mark.e2e
def test_burger_menu_admin_login_reauth():
    base_url = resolve_base_url()
    secret = resolve_secret()
    admin_pw = resolve_admin_password()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        add_secret_cookie(context, base_url, secret)
        page = context.new_page()
        page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=20000)

        page.click("#header-menu", timeout=6000)
        page.wait_for_selector("#header-menu-dropdown:not(.hidden)", timeout=4000)

        page.click("#admin-button-menu", timeout=4000)
        wait_for_modal_open(page)

        page.fill("#admin-password", "wrong-pass")
        page.click("#admin-login")
        page.wait_for_timeout(500)
        status_text = page.inner_text("#admin-modal-status")
        assert any(word in status_text.lower() for word in ["fehl", "ungültig", "login"])
        label_text = page.inner_text("#admin-status-label")
        assert "aus" in label_text.lower()

        page.fill("#admin-password", admin_pw)
        page.click("#admin-login")
        page.wait_for_selector("#admin-modal", state="hidden", timeout=5000)

        page.click("#header-menu", timeout=6000)
        page.wait_for_selector("#header-menu-dropdown:not(.hidden)", timeout=4000)
        page.click("#admin-button-menu", timeout=4000)
        wait_for_modal_open(page)
        pw_again = page.eval_on_selector("#admin-password", "el => el.value")
        assert pw_again == ""
        label_after = page.inner_text("#admin-status-label")
        assert "aus" in label_after.lower()
        page.click("#admin-close")
        page.wait_for_selector("#admin-modal", state="hidden", timeout=5000)

        browser.close()


@pytest.mark.e2e
def test_send_mode_layout_and_sequence():
    base_url = resolve_base_url()
    secret = resolve_secret()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        add_secret_cookie(context, base_url, secret)
        page = context.new_page()
        page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=20000)

        page.wait_for_selector("#zen-toggle", timeout=4000)
        page.click("#zen-toggle")
        page.wait_for_function("() => document.documentElement.getAttribute('data-zen') === 'true'", timeout=5000)

        search_height = page.eval_on_selector(".search-bar", "el => el ? el.offsetHeight : 0")
        assert search_height > 20
        menu_visible = page.is_visible("#header-menu")
        assert menu_visible is False
        theme_visible = page.is_visible("#theme-toggle-header")
        assert theme_visible is False
        toggle_parent = page.evaluate("() => { const t = document.getElementById('zen-toggle'); return t?.parentElement?.id || ''; }")
        assert toggle_parent == "zen-slot"
        title_visible = page.is_visible(".header-title")
        assert title_visible is False

        page.click("#zen-toggle")
        page.wait_for_function("() => document.documentElement.getAttribute('data-zen') === 'false'", timeout=5000)
        menu_visible_after = page.is_visible("#header-menu")
        assert menu_visible_after is True

        page.click("#header-menu", timeout=6000)
        page.wait_for_selector("#header-menu-dropdown:not(.hidden)", timeout=4000)
        page.click("#admin-button-menu", timeout=4000)
        wait_for_modal_open(page)
        page.click("#admin-close")
        page.wait_for_selector("#admin-modal", state="hidden", timeout=5000)

        page.click("#zen-toggle")
        page.wait_for_function("() => document.documentElement.getAttribute('data-zen') === 'true'", timeout=5000)
        page.click("#zen-toggle")
        page.wait_for_function("() => document.documentElement.getAttribute('data-zen') === 'false'", timeout=5000)

        page.click("#header-menu", timeout=6000)
        page.wait_for_selector("#header-menu-dropdown:not(.hidden)", timeout=4000)

        browser.close()
