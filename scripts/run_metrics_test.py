import asyncio
import os
import random
import sys
import time
from typing import List

import httpx


BASE_URL = os.getenv("METRICS_BASE_URL", "http://localhost:8000")
APP_SECRET = os.getenv("APP_SECRET", "")
DOC_LIMIT = int(os.getenv("METRICS_DOC_LIMIT", "500") or 500)
TIMEOUT = float(os.getenv("METRICS_TIMEOUT", "15") or 15)
EXT_FILTER = os.getenv("METRICS_EXT_FILTER", "").strip().lower()
MIN_SIZE_MB = float(os.getenv("METRICS_MIN_SIZE_MB", "0") or 0.0)
MAX_SIZE_MB = float(os.getenv("METRICS_MAX_SIZE_MB", "0") or 0.0)
FORCED_RUN_ID = os.getenv("METRICS_TEST_RUN_ID", "").strip()


def _headers(test_run_id: str = "") -> dict:
    hdr = {"X-Metrics-Test": "1"}
    if APP_SECRET:
        hdr["X-App-Secret"] = APP_SECRET
    if test_run_id:
        hdr["X-Test-Run-Id"] = test_run_id
    return hdr


async def fetch_docs(client: httpx.AsyncClient) -> List[dict]:
    params = {"limit": DOC_LIMIT, "offset": 0}
    if EXT_FILTER:
        params["extension"] = EXT_FILTER
    resp = await client.get(f"{BASE_URL}/api/search", params=params, headers=_headers())
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    filtered = []
    for row in results:
        size = row.get("size_bytes") or 0
        if MIN_SIZE_MB and size < MIN_SIZE_MB * 1024 * 1024:
            continue
        if MAX_SIZE_MB and size > MAX_SIZE_MB * 1024 * 1024:
            continue
        filtered.append(row)
    return filtered


async def measure_doc(client: httpx.AsyncClient, doc_id: int, test_run_id: str) -> None:
    meta_start = time.perf_counter()
    meta_res = await client.get(f"{BASE_URL}/api/document/{doc_id}", headers=_headers(test_run_id), timeout=TIMEOUT)
    meta_duration = (time.perf_counter() - meta_start) * 1000
    meta_res.raise_for_status()
    doc = meta_res.json()

    file_start = time.perf_counter()
    async with client.stream(
        "GET",
        f"{BASE_URL}/api/document/{doc_id}/file",
        headers=_headers(test_run_id),
        timeout=TIMEOUT,
    ) as resp:
        ttfb_ms = (time.perf_counter() - file_start) * 1000
        bytes_read = 0
        async for chunk in resp.aiter_bytes():
            bytes_read += len(chunk)
        total_ms = (time.perf_counter() - file_start) * 1000
        status = resp.status_code
    print(
        f"doc={doc_id} size={doc.get('size_bytes')} ext={doc.get('extension')} meta={meta_duration:.1f}ms "
        f"ttfb={ttfb_ms:.1f}ms total={total_ms:.1f}ms bytes={bytes_read} status={status}"
    )


async def main():
    test_run_id = FORCED_RUN_ID or f"run-{int(time.time())}"
    async with httpx.AsyncClient(follow_redirects=True) as client:
        docs = await fetch_docs(client)
        if not docs:
            print("Keine Dokumente gefunden.")
            return
        random.shuffle(docs)
        docs = docs[:DOC_LIMIT]
        ids = [d.get("id") or d.get("doc_id") for d in docs if (d.get("id") or d.get("doc_id")) is not None]
        for doc_id in ids:
            try:
                await measure_doc(client, doc_id, test_run_id)
            except Exception as exc:  # pragma: no cover
                print(f"Fehler bei doc {doc_id}: {exc}", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
