"""
test_llm_client_error_logging.py — Phase 2.5c regression coverage for
llm_client.py's real error-classification/logging contract: every failed
_call_real() invocation writes an llm_call_logs row (is_mock=False) with
one of the controlled error_type values (timeout, rate_limited, http_error,
json_decode_error, validation_error, unknown), and never writes an
llm_response_cache row for a failed call.

Each test drives one real branch of _classify_error()/the except block in
_call_real() by monkeypatching only _make_paced_request — the sole network
seam — so the classification logic itself is exercised for real, not
re-implemented in the test.
"""
import uuid

import httpx
import pytest
from sqlalchemy import text

import llm_client
from agents.reviewer.schema import ReviewerOutput
from models import AgentName


def _make_groq_response(status_code: int, json_body: dict | None = None) -> httpx.Response:
    request = httpx.Request("POST", llm_client.GROQ_URL)
    return httpx.Response(status_code, json=json_body if json_body is not None else {}, request=request)


async def _latest_log_row(engine):
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT is_mock, error, error_type FROM llm_call_logs ORDER BY id DESC LIMIT 1")
        )
        return result.fetchone()


async def _assert_no_cache_row(engine, wcag_rule: str) -> None:
    async with engine.connect() as conn:
        count = (await conn.execute(
            text("SELECT count(*) FROM llm_response_cache WHERE wcag_rule = :r"), {"r": wcag_rule}
        )).scalar()
    assert count == 0


async def test_error_logging_timeout(test_engine, monkeypatch):
    wcag_rule = f"error-test-timeout-{uuid.uuid4().hex[:12]}"

    async def fake_request(payload, headers):
        raise httpx.TimeoutException("simulated timeout")

    monkeypatch.setattr(llm_client, "_make_paced_request", fake_request)

    with pytest.raises(llm_client.LlmCallError):
        await llm_client._call_real(AgentName.Reviewer, wcag_rule, '<img src="x.jpg">', "sys", "user", ReviewerOutput)

    row = await _latest_log_row(test_engine)
    assert row.is_mock is False
    assert row.error_type == "timeout"
    assert row.error and "TimeoutException" in row.error
    await _assert_no_cache_row(test_engine, wcag_rule)


async def test_error_logging_rate_limited(test_engine, monkeypatch):
    wcag_rule = f"error-test-429-{uuid.uuid4().hex[:12]}"

    async def fake_request(payload, headers):
        return _make_groq_response(429), 5

    monkeypatch.setattr(llm_client, "_make_paced_request", fake_request)

    with pytest.raises(llm_client.LlmCallError):
        await llm_client._call_real(AgentName.Reviewer, wcag_rule, '<img src="x.jpg">', "sys", "user", ReviewerOutput)

    row = await _latest_log_row(test_engine)
    assert row.is_mock is False
    assert row.error_type == "rate_limited"
    assert row.error
    await _assert_no_cache_row(test_engine, wcag_rule)


async def test_error_logging_http_error(test_engine, monkeypatch):
    wcag_rule = f"error-test-500-{uuid.uuid4().hex[:12]}"

    async def fake_request(payload, headers):
        return _make_groq_response(500), 5

    monkeypatch.setattr(llm_client, "_make_paced_request", fake_request)

    with pytest.raises(llm_client.LlmCallError):
        await llm_client._call_real(AgentName.Reviewer, wcag_rule, '<img src="x.jpg">', "sys", "user", ReviewerOutput)

    row = await _latest_log_row(test_engine)
    assert row.is_mock is False
    assert row.error_type == "http_error"
    assert row.error
    await _assert_no_cache_row(test_engine, wcag_rule)


async def test_error_logging_json_decode_error(test_engine, monkeypatch):
    wcag_rule = f"error-test-jsondecode-{uuid.uuid4().hex[:12]}"

    async def fake_request(payload, headers):
        json_body = {"choices": [{"message": {"content": "no braces here"}}], "usage": {"total_tokens": 10}}
        return _make_groq_response(200, json_body), 5

    monkeypatch.setattr(llm_client, "_make_paced_request", fake_request)

    with pytest.raises(llm_client.LlmCallError):
        await llm_client._call_real(AgentName.Reviewer, wcag_rule, '<img src="x.jpg">', "sys", "user", ReviewerOutput)

    row = await _latest_log_row(test_engine)
    assert row.is_mock is False
    assert row.error_type == "json_decode_error"
    assert row.error
    await _assert_no_cache_row(test_engine, wcag_rule)


async def test_error_logging_validation_error(test_engine, monkeypatch):
    wcag_rule = f"error-test-validation-{uuid.uuid4().hex[:12]}"

    async def fake_request(payload, headers):
        json_body = {"choices": [{"message": {"content": '{"foo": "bar"}'}}], "usage": {"total_tokens": 10}}
        return _make_groq_response(200, json_body), 5

    monkeypatch.setattr(llm_client, "_make_paced_request", fake_request)

    with pytest.raises(llm_client.LlmCallError):
        await llm_client._call_real(AgentName.Reviewer, wcag_rule, '<img src="x.jpg">', "sys", "user", ReviewerOutput)

    row = await _latest_log_row(test_engine)
    assert row.is_mock is False
    assert row.error_type == "validation_error"
    assert row.error
    await _assert_no_cache_row(test_engine, wcag_rule)


async def test_error_logging_unknown(test_engine, monkeypatch):
    wcag_rule = f"error-test-unknown-{uuid.uuid4().hex[:12]}"

    async def fake_request(payload, headers):
        # No "choices" key at all -> data["choices"][0] raises a bare
        # KeyError, which _classify_error doesn't recognize -> "unknown".
        json_body = {"usage": {"total_tokens": 5}}
        return _make_groq_response(200, json_body), 5

    monkeypatch.setattr(llm_client, "_make_paced_request", fake_request)

    with pytest.raises(llm_client.LlmCallError):
        await llm_client._call_real(AgentName.Reviewer, wcag_rule, '<img src="x.jpg">', "sys", "user", ReviewerOutput)

    row = await _latest_log_row(test_engine)
    assert row.is_mock is False
    assert row.error_type == "unknown"
    assert row.error and "KeyError" in row.error
    await _assert_no_cache_row(test_engine, wcag_rule)
