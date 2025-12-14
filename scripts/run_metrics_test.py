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


def _headers(test_run_id: str = "") -> dict:
    hdr = {"X-Metrics-Test": "1"}
    if APP_SECRET:
        hdr["X-App-Secret"] = APP_SECRET
    if test_run_id:
        hdr["X-Test-Run-Id"] = test_run_id
    return hdr


async def fetch_docs(client: httpx.AsyncClient) -> List[int]:
    params = {"limit": DOC_LIMIT, "offset": 0}
    resp = await client.get(f"{BASE_URL}/api/search", params=params, headers=_headers())
    resp.raise_for_status()
    data = resp.json()
    ids = [row.get("id") or row.get("doc_id") for row in data.get("results", [])]
    return [i for i in ids if i is not None]


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
    test_run_id = f"run-{int(time.time())}"
    async with httpx.AsyncClient(follow_redirects=True) as client:
        ids = await fetch_docs(client)
        if not ids:
            print("Keine Dokumente gefunden.")
            return
        random.shuffle(ids)
        ids = ids[:DOC_LIMIT]
        for doc_id in ids:
            try:
                await measure_doc(client, doc_id, test_run_id)
            except Exception as exc:  # pragma: no cover
                print(f"Fehler bei doc {doc_id}: {exc}", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
