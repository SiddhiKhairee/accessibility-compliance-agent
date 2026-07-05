"""
api_standalone_test.py — manual verification script, not a permanent test
suite. Posts scan requests for a few real public URLs against a locally
running API and polls GET /scan/{id} until each reaches a terminal status.

Prereqs (run manually, in order, before this script):
  docker compose up -d postgres
  cd backend && alembic upgrade head
  cd backend/app && uvicorn main:app --port 8000   (separate terminal)

Usage: python api_standalone_test.py
"""
import json
import time
import urllib.request

BASE_URL = "http://127.0.0.1:8000"
TEST_URLS = ["https://www.usa.gov", "https://news.ycombinator.com", "https://example.com"]


def post_scan(url: str) -> int:
    req = urllib.request.Request(
        f"{BASE_URL}/scan",
        data=json.dumps({"url": url}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["scan_id"]


def get_scan(scan_id: int) -> dict:
    with urllib.request.urlopen(f"{BASE_URL}/scan/{scan_id}") as resp:
        return json.loads(resp.read())


def main() -> None:
    scan_ids = {url: post_scan(url) for url in TEST_URLS}
    print("Submitted scans:", scan_ids)

    pending = set(scan_ids.values())
    while pending:
        time.sleep(3)
        for scan_id in list(pending):
            scan = get_scan(scan_id)
            if scan["status"] in ("done", "failed"):
                pending.discard(scan_id)
                total = sum(len(p["violations"]) for p in scan["pages"])
                loaded = sum(1 for p in scan["pages"] if p["status"] == "loaded")
                print(
                    f"scan {scan_id}: status={scan['status']} "
                    f"pages={len(scan['pages'])} loaded={loaded} violations={total}"
                )


if __name__ == "__main__":
    main()
