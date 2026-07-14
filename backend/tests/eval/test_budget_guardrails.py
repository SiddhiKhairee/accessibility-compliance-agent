"""
test_budget_guardrails.py — Phase 5 coverage for eval_runner.py's
budget-threshold and LLM_MOCK hard-refuse logic. No real Groq calls: the
pure threshold function needs none, and the DB-counting function is tested
against real LlmCallLog rows inserted directly (same before/after-delta
convention test_cost_report.py uses, since llm_call_logs is a real,
persistent, never-truncated table shared across the whole test suite).
"""
import uuid
from datetime import datetime, timedelta, timezone

import eval_runner
import pytest
from db import async_session_factory
from models import AgentName, LlmCallLog


def test_should_stop_for_budget_under_threshold():
    assert eval_runner.should_stop_for_budget(899, 1000, 0.9) is False


def test_should_stop_for_budget_at_threshold():
    assert eval_runner.should_stop_for_budget(900, 1000, 0.9) is True


def test_should_stop_for_budget_over_threshold():
    assert eval_runner.should_stop_for_budget(950, 1000, 0.9) is True


def test_assert_llm_not_mocked_raises_when_mocked(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    with pytest.raises(eval_runner.LlmMockEnabledError):
        eval_runner._assert_llm_not_mocked()


def test_assert_llm_not_mocked_passes_when_unmocked(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "false")
    eval_runner._assert_llm_not_mocked()  # must not raise


async def _insert_call_log(
    *, model_used: str, is_mock: bool, cache_hit: bool, created_at: datetime,
) -> None:
    async with async_session_factory() as db:
        db.add(LlmCallLog(
            agent_name=AgentName.Reviewer, latency_ms=100, tokens_used=50,
            model_used=model_used, cache_hit=cache_hit, is_mock=is_mock,
            confidence_score=0.9, created_at=created_at,
        ))
        await db.commit()


async def test_count_real_calls_today_counts_only_real_uncached_todays_calls_for_model():
    model = f"test-model-{uuid.uuid4().hex[:12]}"
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    today_9am = now.replace(hour=9)
    yesterday = now - timedelta(days=1)

    async with async_session_factory() as db:
        before = await eval_runner.count_real_calls_today(db, model=model, now=now)
    assert before == 0  # uuid-suffixed model, guaranteed no pre-existing rows

    await _insert_call_log(model_used=model, is_mock=False, cache_hit=False, created_at=today_9am)
    await _insert_call_log(model_used=model, is_mock=False, cache_hit=False, created_at=today_9am)
    # Should NOT count:
    await _insert_call_log(model_used=model, is_mock=True, cache_hit=False, created_at=today_9am)
    await _insert_call_log(model_used=model, is_mock=False, cache_hit=True, created_at=today_9am)
    await _insert_call_log(model_used=model, is_mock=False, cache_hit=False, created_at=yesterday)
    await _insert_call_log(model_used=f"{model}-other", is_mock=False, cache_hit=False, created_at=today_9am)

    async with async_session_factory() as db:
        after = await eval_runner.count_real_calls_today(db, model=model, now=now)
    assert after == 2


async def test_count_real_calls_today_defaults_to_reviewer_model_and_real_now():
    # Sanity check the default `model` param resolves to llm_client.MODEL_NAME
    # and `now=None` doesn't raise (uses the real clock) — not asserting an
    # exact count against the shared table, just that it runs cleanly.
    async with async_session_factory() as db:
        count = await eval_runner.count_real_calls_today(db)
    assert isinstance(count, int)
    assert count >= 0
