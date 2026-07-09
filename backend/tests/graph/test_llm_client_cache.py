"""
test_llm_client_cache.py — Phase 2.5c regression coverage for the
Reviewer-only persistent cache (llm_response_cache) in llm_client.py.

Calls _call_real() directly (the cache is only reachable there — LLM_MOCK
short-circuits to _call_mock before the cache check) with the sole network
seam, _make_paced_request, monkeypatched. Each test uses a uuid-suffixed
wcag_rule so cache_key is unique per test invocation: llm_response_cache is
a real persistent table on the shared test DB (not truncated between
pytest runs, same as every other table in this suite), so reusing a fixed
wcag_rule/html_snippet across runs would let a *previous* run's cached row
produce a false cache hit on what this test expects to be the first,
network-hitting call.
"""
import uuid

import httpx
from sqlalchemy import text

import llm_client
from agents.developer.schema import DeveloperOutput
from agents.reviewer.schema import ReviewerOutput
from models import AgentName


def _make_groq_response(status_code: int, content: str | None = None, tokens: int = 42) -> httpx.Response:
    request = httpx.Request("POST", llm_client.GROQ_URL)
    if content is None:
        json_body = {}
    else:
        json_body = {"choices": [{"message": {"content": content}}], "usage": {"total_tokens": tokens}}
    return httpx.Response(status_code, json=json_body, request=request)


async def test_repeated_identical_input_is_cache_hit(test_engine, monkeypatch):
    wcag_rule = f"cache-test-repeat-{uuid.uuid4().hex[:12]}"
    html_snippet = '<img src="cache1.jpg">'
    call_count = {"n": 0}

    async def fake_request(model, payload, headers):
        call_count["n"] += 1
        content = '{"confirmed": true, "confidence_score": 0.9, "reasoning": "cache test"}'
        return _make_groq_response(200, content), 5

    monkeypatch.setattr(llm_client, "_make_paced_request", fake_request)

    result1 = await llm_client._call_real(
        AgentName.Reviewer, wcag_rule, html_snippet, "sys", "user", ReviewerOutput
    )
    assert call_count["n"] == 1
    assert result1.confidence_score == 0.9

    async with test_engine.connect() as conn:
        cache_rows = (await conn.execute(
            text("SELECT count(*) FROM llm_response_cache WHERE wcag_rule = :r"), {"r": wcag_rule}
        )).scalar()
        first_cache_hit = (await conn.execute(
            text("SELECT cache_hit FROM llm_call_logs ORDER BY id DESC LIMIT 1")
        )).scalar()
    assert cache_rows == 1
    assert first_cache_hit is False

    async def fake_request_should_not_be_called(model, payload, headers):
        raise AssertionError("network should not be called on a cache hit")

    monkeypatch.setattr(llm_client, "_make_paced_request", fake_request_should_not_be_called)

    result2 = await llm_client._call_real(
        AgentName.Reviewer, wcag_rule, html_snippet, "sys", "user", ReviewerOutput
    )
    assert call_count["n"] == 1  # unchanged — second call never hit the network
    assert result2.confidence_score == 0.9

    async with test_engine.connect() as conn:
        second_cache_hit = (await conn.execute(
            text("SELECT cache_hit FROM llm_call_logs ORDER BY id DESC LIMIT 1")
        )).scalar()
    assert second_cache_hit is True


async def test_whitespace_and_tag_case_normalize_to_same_cache_key(test_engine, monkeypatch):
    wcag_rule = f"cache-test-norm-{uuid.uuid4().hex[:12]}"
    html_a = '<IMG   SRC="same.jpg">'
    html_b = '<img src="same.jpg">'
    call_count = {"n": 0}

    async def fake_request(model, payload, headers):
        call_count["n"] += 1
        content = '{"confirmed": true, "confidence_score": 0.8, "reasoning": "norm test"}'
        return _make_groq_response(200, content), 5

    monkeypatch.setattr(llm_client, "_make_paced_request", fake_request)

    await llm_client._call_real(AgentName.Reviewer, wcag_rule, html_a, "sys", "user", ReviewerOutput)
    assert call_count["n"] == 1

    async def fake_request_should_not_be_called(model, payload, headers):
        raise AssertionError("second call (whitespace/case variant) should hit cache, not network")

    monkeypatch.setattr(llm_client, "_make_paced_request", fake_request_should_not_be_called)

    result2 = await llm_client._call_real(AgentName.Reviewer, wcag_rule, html_b, "sys", "user", ReviewerOutput)
    assert result2.confidence_score == 0.8

    async with test_engine.connect() as conn:
        count = (await conn.execute(
            text("SELECT count(*) FROM llm_response_cache WHERE wcag_rule = :r"), {"r": wcag_rule}
        )).scalar()
    assert count == 1


async def test_different_attribute_value_does_not_collide(test_engine, monkeypatch):
    wcag_rule = f"cache-test-diff-{uuid.uuid4().hex[:12]}"
    html_a = '<img src="x.jpg">'
    html_b = '<img src="y.jpg">'
    call_count = {"n": 0}

    async def fake_request(model, payload, headers):
        call_count["n"] += 1
        content = '{"confirmed": true, "confidence_score": 0.5, "reasoning": "diff test"}'
        return _make_groq_response(200, content), 5

    monkeypatch.setattr(llm_client, "_make_paced_request", fake_request)

    await llm_client._call_real(AgentName.Reviewer, wcag_rule, html_a, "sys", "user", ReviewerOutput)
    await llm_client._call_real(AgentName.Reviewer, wcag_rule, html_b, "sys", "user", ReviewerOutput)

    assert call_count["n"] == 2  # both calls hit the network — no false cache hit

    async with test_engine.connect() as conn:
        rows = (await conn.execute(
            text("SELECT cache_key FROM llm_response_cache WHERE wcag_rule = :r"), {"r": wcag_rule}
        )).fetchall()
    assert len(rows) == 2
    assert rows[0][0] != rows[1][0]


async def test_developer_cache_hit_overrides_target_selector(test_engine, monkeypatch):
    """Phase 3: Developer is now cacheable, but target_selector is a
    verbatim copy of the input (not independently generated content) — a
    cache hit must always use the CURRENT call's element_selector, never
    the cached value, since the same fix can legitimately apply to two
    different violations with two different selectors."""
    wcag_rule = f"cache-test-developer-{uuid.uuid4().hex[:12]}"
    html_snippet = '<img src="dev-cache.jpg">'
    call_count = {"n": 0}

    async def fake_request(model, payload, headers):
        call_count["n"] += 1
        content = '{"proposed_code_diff": "<img src=\\"dev-cache.jpg\\" alt=\\"desc\\">", "target_selector": "selector-A"}'
        return _make_groq_response(200, content), 5

    monkeypatch.setattr(llm_client, "_make_paced_request", fake_request)

    result1 = await llm_client._call_real(
        AgentName.Developer, wcag_rule, html_snippet, "sys", "user", DeveloperOutput,
        element_selector="selector-A",
    )
    assert call_count["n"] == 1
    assert result1.target_selector == "selector-A"

    async def fake_request_should_not_be_called(model, payload, headers):
        raise AssertionError("network should not be called on a cache hit")

    monkeypatch.setattr(llm_client, "_make_paced_request", fake_request_should_not_be_called)

    result2 = await llm_client._call_real(
        AgentName.Developer, wcag_rule, html_snippet, "sys", "user", DeveloperOutput,
        element_selector="selector-B",
    )
    assert call_count["n"] == 1  # cache hit, network not re-invoked
    assert result2.target_selector == "selector-B"  # overridden, not the cached "selector-A"
    assert result2.proposed_code_diff == result1.proposed_code_diff  # the actual fix content is still reused
