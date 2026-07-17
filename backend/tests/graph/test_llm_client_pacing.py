"""
test_llm_client_pacing.py — Phase 5 regression coverage for the
MIN_CALL_INTERVAL_S fixed-delay pacing fix in llm_client.py.

Every prior llm_client.py test monkeypatches _make_paced_request away
wholesale, so none of them ever exercise the pacing internals themselves.
These tests go one level lower: mock _get_http_client's returned client so
_make_paced_request's own pace-check/request/state-update logic runs for
real, and monkeypatch the module's _monotonic/_sleep aliases with a fake
clock so elapsed-time math is deterministic and instant (no real waiting).
"""
import uuid

import httpx

import llm_client
from agents.reviewer.schema import ReviewerOutput
from models import AgentName


class _FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _FakeHttpClient:
    def __init__(self, responses: list[httpx.Response]):
        self._responses = list(responses)

    async def post(self, url, json=None, headers=None, timeout=None):
        return self._responses.pop(0)


def _healthy_response() -> httpx.Response:
    json_body = {
        "choices": [{"message": {"content": '{"confirmed": true, "confidence_score": 0.9, "reasoning": "ok"}'}}],
        "usage": {"total_tokens": 10},
    }
    # Well above TOKEN_SAFETY_MARGIN (1500) so the existing reactive sleep
    # never fires -- isolates the new floor-delay behavior under test.
    headers = {"x-ratelimit-remaining-tokens": "5900", "x-ratelimit-reset-tokens": "60s"}
    return httpx.Response(200, json=json_body, headers=headers, request=httpx.Request("POST", llm_client.GROQ_URL))


async def test_first_call_for_a_fresh_model_never_floor_delays(monkeypatch):
    model = f"test-model-{uuid.uuid4().hex[:8]}"
    clock = _FakeClock()
    monkeypatch.setattr(llm_client, "_monotonic", clock.monotonic)
    monkeypatch.setattr(llm_client, "_sleep", clock.sleep)
    monkeypatch.setattr(llm_client, "_get_http_client", lambda: _FakeHttpClient([_healthy_response()]))

    wcag_rule = f"pacing-test-{uuid.uuid4().hex[:12]}"
    await llm_client._call_real(
        AgentName.Reviewer, wcag_rule, '<img src="x.jpg">', "sys", "user", ReviewerOutput, model=model,
    )

    assert clock.sleeps == []


async def test_second_back_to_back_call_is_floor_delayed(monkeypatch):
    model = f"test-model-{uuid.uuid4().hex[:8]}"
    clock = _FakeClock()
    monkeypatch.setattr(llm_client, "_monotonic", clock.monotonic)
    monkeypatch.setattr(llm_client, "_sleep", clock.sleep)
    monkeypatch.setattr(
        llm_client, "_get_http_client", lambda: _FakeHttpClient([_healthy_response(), _healthy_response()]),
    )

    async def _real_call():
        wcag_rule = f"pacing-test-{uuid.uuid4().hex[:12]}"
        await llm_client._call_real(
            AgentName.Reviewer, wcag_rule, '<img src="x.jpg">', "sys", "user", ReviewerOutput, model=model,
        )

    await _real_call()
    await _real_call()

    # Zero real time elapsed between the two calls (the fake clock only
    # advances via clock.sleep), so the second call must be floor-delayed
    # by exactly MIN_CALL_INTERVAL_S -- the reactive margin check never
    # fires (remaining=5900 stays well above TOKEN_SAFETY_MARGIN), so this
    # sleep can only be the new floor delay.
    assert clock.sleeps == [llm_client.MIN_CALL_INTERVAL_S]


async def test_no_floor_delay_when_enough_real_time_already_passed(monkeypatch):
    model = f"test-model-{uuid.uuid4().hex[:8]}"
    clock = _FakeClock()
    monkeypatch.setattr(llm_client, "_monotonic", clock.monotonic)
    monkeypatch.setattr(llm_client, "_sleep", clock.sleep)
    monkeypatch.setattr(
        llm_client, "_get_http_client", lambda: _FakeHttpClient([_healthy_response(), _healthy_response()]),
    )

    wcag_rule_1 = f"pacing-test-{uuid.uuid4().hex[:12]}"
    await llm_client._call_real(
        AgentName.Reviewer, wcag_rule_1, '<img src="x.jpg">', "sys", "user", ReviewerOutput, model=model,
    )

    # Simulate real wall-clock time passing between calls (e.g. other work
    # in the caller's loop) well beyond MIN_CALL_INTERVAL_S.
    clock.now += 10.0

    wcag_rule_2 = f"pacing-test-{uuid.uuid4().hex[:12]}"
    await llm_client._call_real(
        AgentName.Reviewer, wcag_rule_2, '<img src="x.jpg">', "sys", "user", ReviewerOutput, model=model,
    )

    assert clock.sleeps == []


async def test_pacing_is_scoped_per_model(monkeypatch):
    """A floor delay recorded for one model must not affect a different
    model -- mirrors the existing per-model keying of _remaining_tokens/
    _reset_at_monotonic (Groq tracks each model's budget independently)."""
    model_a = f"test-model-a-{uuid.uuid4().hex[:8]}"
    model_b = f"test-model-b-{uuid.uuid4().hex[:8]}"
    clock = _FakeClock()
    monkeypatch.setattr(llm_client, "_monotonic", clock.monotonic)
    monkeypatch.setattr(llm_client, "_sleep", clock.sleep)
    monkeypatch.setattr(
        llm_client, "_get_http_client", lambda: _FakeHttpClient([_healthy_response(), _healthy_response()]),
    )

    wcag_rule_1 = f"pacing-test-{uuid.uuid4().hex[:12]}"
    await llm_client._call_real(
        AgentName.Reviewer, wcag_rule_1, '<img src="x.jpg">', "sys", "user", ReviewerOutput, model=model_a,
    )
    wcag_rule_2 = f"pacing-test-{uuid.uuid4().hex[:12]}"
    await llm_client._call_real(
        AgentName.Reviewer, wcag_rule_2, '<img src="x.jpg">', "sys", "user", ReviewerOutput, model=model_b,
    )

    assert clock.sleeps == []
