"""
test_graph_sequence.py — Phase 2.5c regression coverage for graph.py's
4-node sequence (Reviewer -> Impact -> Developer -> Verifier) under
LLM_MOCK=true.

Queries llm_call_logs directly (via test_engine) rather than trusting
graph.ainvoke()'s return value alone, so these tests prove the *real* call
path was taken (agent_name/is_mock/cache_hit columns), not just that the
mock schema happened to validate.
"""
import os

from sqlalchemy import text

from agents.developer.schema import DeveloperOutput
from agents.impact.schema import ImpactOutput
from agents.reviewer.schema import ReviewerOutput
from agents.verifier.schema import VerifierOutput
from graph import impact_node, reasoning_graph, verifier_node


async def _max_log_id(engine) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM llm_call_logs"))
        return result.scalar()


async def _new_logs(engine, since_id: int):
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT agent_name, is_mock, cache_hit, error_type FROM llm_call_logs "
                "WHERE id > :since ORDER BY id"
            ),
            {"since": since_id},
        )
        return result.fetchall()


async def test_full_graph_sequence_llm_mock(test_engine):
    before_id = await _max_log_id(test_engine)

    v = {
        "id": 999903,
        "wcag_rule": "image-alt",
        "element_selector": "img.hero",
        "html_snippet": '<img class="hero" src="x.jpg">',
        "message": "Image missing alt attribute",
        "page_url": "https://example.com/about",  # not a critical-path pattern
    }
    final_state = await reasoning_graph.ainvoke({"violation": v})

    assert isinstance(final_state["reviewer_result"], ReviewerOutput)
    assert isinstance(final_state["impact_result"], ImpactOutput)
    assert isinstance(final_state["developer_result"], DeveloperOutput)
    assert isinstance(final_state["verifier_result"], VerifierOutput)
    assert final_state["verifier_result"].status == "pending_verification"

    new_logs = await _new_logs(test_engine, before_id)
    by_agent = {row.agent_name: row for row in new_logs}
    assert set(by_agent) == {"Reviewer", "Impact", "Developer"}
    for row in new_logs:
        assert row.is_mock is True
        assert row.cache_hit is False


async def test_impact_node_critical_path_heuristic_skips_llm(test_engine):
    before_id = await _max_log_id(test_engine)

    v = {
        "id": 999902,
        "wcag_rule": "label",
        "element_selector": "input#foo",
        "html_snippet": '<input id="foo">',
        "message": "Form input missing label",
        "page_url": "https://example.com/checkout/step2",
    }
    result = await impact_node({"violation": v})
    impact_result = result["impact_result"]

    assert impact_result.is_critical_path is True
    assert impact_result.business_risk_score == 1.0
    assert "checkout" in impact_result.reasoning_text

    new_logs = await _new_logs(test_engine, before_id)
    assert all(row.agent_name != "Impact" for row in new_logs)


async def test_verifier_is_structural_stub(test_engine):
    before_id = await _max_log_id(test_engine)

    result = await verifier_node({})

    assert result["verifier_result"].status == "pending_verification"
    assert await _new_logs(test_engine, before_id) == []
