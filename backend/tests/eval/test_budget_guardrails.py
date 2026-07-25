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
    *, model_used: str, is_mock: bool, cache_hit: bool, created_at: datetime, tokens_used: int = 50,
) -> None:
    async with async_session_factory() as db:
        db.add(LlmCallLog(
            agent_name=AgentName.Reviewer, latency_ms=100, tokens_used=tokens_used,
            model_used=model_used, cache_hit=cache_hit, is_mock=is_mock,
            confidence_score=0.9, created_at=created_at,
        ))
        await db.commit()


async def test_count_real_calls_today_counts_only_real_uncached_calls_in_rolling_24h_for_model():
    model = f"test-model-{uuid.uuid4().hex[:12]}"
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    ten_hours_ago = now - timedelta(hours=10)
    outside_window = now - timedelta(hours=25)

    async with async_session_factory() as db:
        before = await eval_runner.count_real_calls_today(db, model=model, now=now)
    assert before == 0  # uuid-suffixed model, guaranteed no pre-existing rows

    await _insert_call_log(model_used=model, is_mock=False, cache_hit=False, created_at=ten_hours_ago)
    await _insert_call_log(model_used=model, is_mock=False, cache_hit=False, created_at=ten_hours_ago)
    # Should NOT count:
    await _insert_call_log(model_used=model, is_mock=True, cache_hit=False, created_at=ten_hours_ago)
    await _insert_call_log(model_used=model, is_mock=False, cache_hit=True, created_at=ten_hours_ago)
    await _insert_call_log(model_used=model, is_mock=False, cache_hit=False, created_at=outside_window)
    await _insert_call_log(model_used=f"{model}-other", is_mock=False, cache_hit=False, created_at=ten_hours_ago)

    async with async_session_factory() as db:
        after = await eval_runner.count_real_calls_today(db, model=model, now=now)
    assert after == 2


async def test_count_real_calls_today_uses_rolling_window_not_calendar_day():
    """Regression for design.md Section 14m: a call from a few hours before
    UTC midnight (a different *calendar* day than `now`) must still count,
    since it's well within the real rolling 24h window Groq actually
    enforces. The pre-fix calendar-midnight boundary would have wrongly
    excluded it, letting a resume think it had a fresh budget it didn't."""
    model = f"test-model-{uuid.uuid4().hex[:12]}"
    now = datetime(2026, 6, 15, 0, 20, tzinfo=timezone.utc)  # 20 min into a new UTC day
    previous_calendar_day_but_within_24h = now - timedelta(hours=2)  # 2026-06-14, ~5h before this window's cutoff

    await _insert_call_log(model_used=model, is_mock=False, cache_hit=False, created_at=previous_calendar_day_but_within_24h)

    async with async_session_factory() as db:
        count = await eval_runner.count_real_calls_today(db, model=model, now=now)
    assert count == 1


async def test_count_real_calls_today_defaults_to_reviewer_model_and_real_now():
    # Sanity check the default `model` param resolves to llm_client.MODEL_NAME
    # and `now=None` doesn't raise (uses the real clock) — not asserting an
    # exact count against the shared table, just that it runs cleanly.
    async with async_session_factory() as db:
        count = await eval_runner.count_real_calls_today(db)
    assert isinstance(count, int)
    assert count >= 0


async def test_sum_tokens_used_today_sums_only_real_uncached_tokens_in_rolling_24h_for_model():
    model = f"test-model-{uuid.uuid4().hex[:12]}"
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    ten_hours_ago = now - timedelta(hours=10)
    outside_window = now - timedelta(hours=25)

    async with async_session_factory() as db:
        before = await eval_runner.sum_tokens_used_today(db, model=model, now=now)
    assert before == 0  # coalesce(sum(...), 0) on an empty result, not None

    # Distinct tokens_used values on the two "should count" rows so the
    # assertion proves summation, not a count-shaped coincidence.
    await _insert_call_log(model_used=model, is_mock=False, cache_hit=False, created_at=ten_hours_ago, tokens_used=1000)
    await _insert_call_log(model_used=model, is_mock=False, cache_hit=False, created_at=ten_hours_ago, tokens_used=2000)
    # Should NOT count (non-zero tokens_used so a bug that summed
    # everything would visibly fail):
    await _insert_call_log(model_used=model, is_mock=True, cache_hit=False, created_at=ten_hours_ago, tokens_used=500)
    await _insert_call_log(model_used=model, is_mock=False, cache_hit=True, created_at=ten_hours_ago, tokens_used=500)
    await _insert_call_log(model_used=model, is_mock=False, cache_hit=False, created_at=outside_window, tokens_used=500)
    await _insert_call_log(
        model_used=f"{model}-other", is_mock=False, cache_hit=False, created_at=ten_hours_ago, tokens_used=500,
    )

    async with async_session_factory() as db:
        after = await eval_runner.sum_tokens_used_today(db, model=model, now=now)
    assert after == 3000


async def test_sum_tokens_used_today_uses_rolling_window_not_calendar_day():
    """Regression for design.md Section 14m -- see the matching
    count_real_calls_today test for the real-world scenario this locks in:
    a fresh UTC calendar day must not report a fresh token budget if heavy
    usage happened within the last real 24 hours."""
    model = f"test-model-{uuid.uuid4().hex[:12]}"
    now = datetime(2026, 6, 15, 0, 20, tzinfo=timezone.utc)
    previous_calendar_day_but_within_24h = now - timedelta(hours=2)

    await _insert_call_log(
        model_used=model, is_mock=False, cache_hit=False,
        created_at=previous_calendar_day_but_within_24h, tokens_used=199000,
    )

    async with async_session_factory() as db:
        tokens = await eval_runner.sum_tokens_used_today(db, model=model, now=now)
    assert tokens == 199000


async def test_sum_tokens_used_today_defaults_to_reviewer_model_and_real_now():
    # Sanity check the default `model` param resolves to llm_client.MODEL_NAME
    # and `now=None` doesn't raise (uses the real clock) — not asserting an
    # exact total against the shared table, just that it runs cleanly.
    async with async_session_factory() as db:
        tokens = await eval_runner.sum_tokens_used_today(db)
    assert isinstance(tokens, int)
    assert tokens >= 0
