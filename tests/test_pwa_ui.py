import pytest


@pytest.mark.e2e
@pytest.mark.smoke
@pytest.mark.pwa
def test_manifest_link_and_fetch(page, base_url):
    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=20000)
    link = page.locator("link[rel='manifest']")
    link.wait_for(state="attached", timeout=5000)
    href = link.get_attribute("href")
    assert href

    manifest_url = href if href.startswith("http") else f"{base_url.rstrip('/')}/{href.lstrip('/')}"
    manifest = page.evaluate(
        """async (url) => {
            const res = await fetch(url);
            const json = await res.json();
            return {
                ok: res.ok,
                contentType: res.headers.get("content-type"),
                json,
            };
        }""",
        manifest_url,
    )
    assert manifest["ok"]
    assert manifest["contentType"].startswith("application/manifest+json")
    icons = manifest["json"].get("icons", [])
    assert any(icon.get("purpose") == "maskable" for icon in icons)
    assert manifest["json"].get("display") == "standalone"


@pytest.mark.e2e
@pytest.mark.smoke
@pytest.mark.pwa
def test_service_worker_registers(page, base_url):
    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=20000)
    registration = page.wait_for_function(
        """async () => {
            if (!('serviceWorker' in navigator)) return null;
            const reg = await navigator.serviceWorker.getRegistration();
            return reg ? { scope: reg.scope } : null;
        }""",
        timeout=15000,
    ).json_value()
    assert registration and registration.get("scope", "").endswith("/")

    page.reload(wait_until="domcontentloaded", timeout=20000)
    controller_active = page.wait_for_function(
        "() => !!(navigator.serviceWorker && navigator.serviceWorker.controller)",
        timeout=8000,
    ).json_value()
    assert controller_active is True
