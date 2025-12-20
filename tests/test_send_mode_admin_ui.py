import pytest
def wait_for_modal_open(page):
    page.wait_for_selector("#admin-modal:not(.hidden)", timeout=6000)


@pytest.mark.e2e
@pytest.mark.smoke
def test_burger_menu_admin_login_reauth(page, base_url, admin_password):
    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=20000)
    always_on = page.evaluate("() => document.documentElement.getAttribute('data-admin-always-on') === 'true'")

    page.click("#header-menu", timeout=6000)
    page.wait_for_selector("#header-menu-dropdown:not(.hidden)", timeout=4000)

    page.click("#admin-button-menu", timeout=4000)
    wait_for_modal_open(page)

    if always_on:
        label_text = page.inner_text("#admin-status-label")
        assert "aktiv" in label_text.lower()
        page.click("#admin-close")
        page.wait_for_selector("#admin-modal", state="hidden", timeout=5000)
        return

    page.fill("#admin-password", "wrong-pass")
    page.click("#admin-login")
    page.wait_for_timeout(500)
    status_text = page.inner_text("#admin-modal-status")
    assert any(word in status_text.lower() for word in ["fehl", "ungültig", "login"])
    label_text = page.inner_text("#admin-status-label")
    assert "aus" in label_text.lower()

    page.fill("#admin-password", admin_password)
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


@pytest.mark.e2e
@pytest.mark.smoke
def test_send_mode_layout_and_sequence(page, base_url):
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
