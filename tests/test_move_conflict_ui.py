import json

import pytest


@pytest.mark.e2e
def test_move_dialog_conflict_retry_flow(page, base_url):
    conflict_seen = {"mode": None}

    def handle_copy(route, request):
        try:
            body = request.post_data_json or {}
        except Exception:
            body = {}
        mode = (body.get("conflict_mode") or "abort").lower()
        conflict_seen["mode"] = mode
        if mode in {"autorename", "overwrite"}:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"status": "ok", "doc_id": 123, "new_path": "/Root/one.txt"}),
            )
            return
        route.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps(
                {
                    "status": "conflict",
                    "code": "CONFLICT",
                    "detail": "Ziel existiert bereits",
                    "conflicts": [{"name": "one.txt", "dest": "/Root/one.txt"}],
                }
            ),
        )

    def handle_tree(route, _request):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"entries": [{"name": "Root", "path": "", "has_children": True, "source": "Root"}]}),
        )

    page.context.route("**/api/files/123/copy", handle_copy)
    page.context.route("**/api/files/tree**", handle_tree)

    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=20000)
    page.evaluate(
        """() => {
            if (typeof showMoveDialog === "function") { showMoveDialog(123, "copy"); }
        }"""
    )
    page.wait_for_selector("#move-dialog:not(.hidden)", timeout=5000)
    page.evaluate(
        """() => {
            moveState.selection = "Root::";
            moveState.currentFolder = "Root::";
            moveState.source = "Root";
            updateMoveTargetPath();
            renderBreadcrumb();
            renderMoveTree();
            const btn = document.getElementById("move-confirm");
            if (btn) btn.disabled = false;
        }"""
    )

    page.click("#move-confirm")
    page.wait_for_selector("#move-conflict-panel:not(.hidden)", timeout=5000)
    conflict_text = page.inner_text("#move-conflict-count")
    assert "Konflikt" in conflict_text

    page.click("#move-conflict-rename")
    page.wait_for_selector("#move-dialog", state="hidden", timeout=6000)
    assert conflict_seen["mode"] == "autorename"
