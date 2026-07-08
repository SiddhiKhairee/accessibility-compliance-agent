"""
test_scan_roundtrip.py — Phase 2.5b regression coverage for the
POST /scan -> GET /scan/{id} API layer. Runs entirely against the test DB
(port 5434, via api/conftest.py's DATABASE_URL override) and the local
test server (fixtures/server.py) — no real internet, no real Groq
(LLM_MOCK=true, already proven by 2.5a's test_llm_mock_forced_in_test_env),
no real dev DB (port 5433).

Uses httpx's ASGITransport (in-process, no real socket) against main.app
directly. Confirmed by reading starlette/background.py and
starlette/responses.py during 2.5b planning: BackgroundTasks execute
*inside* Response.__call__, as part of the same ASGI app(...) coroutine —
so `await client.post("/scan", ...)` only returns once run_scan() (crawl +
detect + the Phase 2 reasoning pass) has fully completed. A bounded-retry
poll against GET /scan/{id} is still used rather than relying on that
detail, matching the project's "no flaky sleep-based wait" rule.
"""
import asyncio
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]


async def _poll_until_terminal(client, scan_id: int, max_attempts: int = 20, interval_s: float = 0.5) -> dict:
    for _ in range(max_attempts):
        resp = await client.get(f"/scan/{scan_id}")
        body = resp.json()
        if body["status"] in ("done", "failed"):
            return body
        await asyncio.sleep(interval_s)
    raise TimeoutError(f"scan {scan_id} did not reach a terminal status")


async def test_scan_roundtrip_persists_violation_to_test_db(api_client, test_server, test_engine):
    url = f"{test_server.base_url}/crawler_site/api_scan_target.html"

    resp = await api_client.post("/scan", json={"url": url, "max_pages": 1, "max_depth": 0})
    assert resp.status_code == 202
    scan_id = resp.json()["scan_id"]

    final = await _poll_until_terminal(api_client, scan_id)
    assert final["status"] == "done"
    assert len(final["pages"]) == 1
    assert final["pages"][0]["status"] == "loaded"

    violations = final["pages"][0]["violations"]
    assert any(v["wcag_rule"] == "image-alt" for v in violations)

    # Confirm against the real test DB directly, not just the API
    # response's own shape.
    async with test_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT v.wcag_rule FROM violations v "
                "JOIN pages p ON v.page_id = p.id "
                "WHERE p.scan_id = :scan_id"
            ),
            {"scan_id": scan_id},
        )
        rules = [row[0] for row in result.fetchall()]
    assert "image-alt" in rules

    # Isolation check: this scan must never have touched the real dev DB
    # (port 5433) — proving isolation, not just asserting silence.
    dev_database_url = dotenv_values(BACKEND_DIR / "app" / ".env").get("DATABASE_URL")
    assert dev_database_url is not None
    dev_engine = create_async_engine(dev_database_url, pool_pre_ping=True)
    try:
        async with dev_engine.connect() as conn:
            result = await conn.execute(text("SELECT id FROM sites WHERE url = :url"), {"url": url})
            assert result.first() is None
    finally:
        await dev_engine.dispose()
