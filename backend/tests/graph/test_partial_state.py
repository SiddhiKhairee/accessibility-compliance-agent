"""
test_partial_state.py — Phase 2.5c regression coverage for the "no partial
state" guarantee (design.md Section 8): a mid-graph reasoning failure must
leave zero rows in impact_assessments/fixes for that violation, and must
not fail the whole scan.

Forces a deterministic failure on the Developer node only, via
monkeypatching llm_client._call_mock (the pre-approved mechanism — see
plan). call_llm() resolves `_call_mock` as a same-module global at call
time, so patching the module attribute intercepts it regardless of how
graph.py imported call_llm; no edits to llm_client.py/graph.py needed.

Runs through main.py's real run_scan (via POST /scan against the local
test server's api_scan_target.html fixture, same pattern as
api/test_scan_roundtrip.py) rather than calling graph.ainvoke() directly,
because graph.py's nodes never write to the DB — the no-partial-state
guarantee is actually enforced by run_scan's try/except-continue around
ainvoke(), so that's the code path that must be exercised.
"""
import asyncio

from sqlalchemy import text

import llm_client
from models import AgentName


async def _poll_until_terminal(client, scan_id: int, max_attempts: int = 20, interval_s: float = 0.5) -> dict:
    for _ in range(max_attempts):
        resp = await client.get(f"/scan/{scan_id}")
        body = resp.json()
        if body["status"] in ("done", "failed"):
            return body
        await asyncio.sleep(interval_s)
    raise TimeoutError(f"scan {scan_id} did not reach a terminal status")


async def test_no_partial_state_on_developer_failure(api_client, test_server, test_engine, monkeypatch):
    original_call_mock = llm_client._call_mock

    async def failing_call_mock(agent_name, schema):
        if agent_name == AgentName.Developer:
            raise llm_client.LlmCallError("forced test failure (Developer) — proving no-partial-state guarantee")
        return await original_call_mock(agent_name, schema)

    monkeypatch.setattr(llm_client, "_call_mock", failing_call_mock)

    async with test_engine.connect() as conn:
        before_id = (await conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM llm_call_logs"))).scalar()

    url = f"{test_server.base_url}/crawler_site/api_scan_target.html"
    resp = await api_client.post("/scan", json={"url": url, "max_pages": 1, "max_depth": 0})
    assert resp.status_code == 202
    scan_id = resp.json()["scan_id"]

    final = await _poll_until_terminal(api_client, scan_id)

    # A per-violation reasoning failure must not fail the whole scan.
    assert final["status"] == "done"
    assert len(final["pages"]) == 1
    violations = final["pages"][0]["violations"]
    assert len(violations) == 1
    violation = violations[0]
    assert violation["wcag_rule"] == "image-alt"

    # Nothing partially written for this violation via the API response.
    assert violation["confidence"] is None
    assert violation["impact_assessment"] is None
    assert violation["fix"] is None

    # Confirm directly against the test DB, not just the API's own shape.
    async with test_engine.connect() as conn:
        impact_count = (await conn.execute(
            text("SELECT count(*) FROM impact_assessments WHERE violation_id = :vid"),
            {"vid": violation["id"]},
        )).scalar()
        fix_count = (await conn.execute(
            text("SELECT count(*) FROM fixes WHERE violation_id = :vid"),
            {"vid": violation["id"]},
        )).scalar()
        confidence = (await conn.execute(
            text("SELECT confidence FROM violations WHERE id = :vid"),
            {"vid": violation["id"]},
        )).scalar()
    assert impact_count == 0
    assert fix_count == 0
    assert confidence is None

    # Reviewer + Impact must have actually run (and logged) before the
    # forced Developer failure — proves the graph got 2 nodes deep, not
    # that it failed immediately at Reviewer.
    async with test_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT agent_name, is_mock, error FROM llm_call_logs "
                "WHERE id > :since ORDER BY id"
            ),
            {"since": before_id},
        )
        new_logs = result.fetchall()
    logged_agents = {row.agent_name for row in new_logs}
    assert logged_agents == {"Reviewer", "Impact"}
    assert all(row.is_mock for row in new_logs)
    assert all(row.error is None for row in new_logs)
