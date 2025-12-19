import os
from pathlib import Path

import httpx
import pytest


def _headers():
    secret = os.getenv("APP_SECRET", "")
    hdrs = {}
    if secret:
        hdrs["X-App-Secret"] = secret
    return hdrs


@pytest.mark.e2e
@pytest.mark.smoke
def test_dashboard_loads_and_status_tile(page, base_url):
    page.goto(f"{base_url}/dashboard", wait_until="domcontentloaded", timeout=20000)
    page.wait_for_selector("#status-pill", timeout=5000)
    text = page.inner_text("#status-pill")
    assert text, "Status-Pill sollte Text enthalten"


@pytest.mark.e2e
@pytest.mark.critical
def test_admin_status_marks_missing_source(base_url):
    if os.getenv("E2E_EXTERNAL") == "1":
        pytest.skip("Externer Lauf: keine Manipulation lokaler Quellen")
    data_root = Path(os.getenv("DATA_CONTAINER_PATH", "data")).resolve()
    demo_root = data_root / "sources" / "demo"
    if not demo_root.exists():
        pytest.skip("Demo-Quelle nicht gefunden")
    temp_root = demo_root.with_name(demo_root.name + "_offline")
    demo_root.rename(temp_root)
    try:
        resp = httpx.get(f"{base_url}/api/admin/status", headers=_headers(), timeout=10.0, trust_env=False)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("sources_ready") is False
        assert data.get("source_issues"), "Quelle offline sollte gemeldet werden"
    finally:
        temp_root.rename(demo_root)


@pytest.mark.e2e
@pytest.mark.critical
def test_auto_index_is_disabled_in_test_mode(base_url):
    resp = httpx.get(f"{base_url}/api/auto-index/status", headers=_headers(), timeout=10.0, trust_env=False)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status", {}).get("running") is False
