"""
llm_client.py — Groq API wrapper for the Phase 2 LangGraph reasoning layer.

Single entry point `call_llm()` used by all three real-LLM nodes (Reviewer,
Impact's ambiguous-URL fallback, Developer). Handles:
  - real-vs-mock dispatch (LLM_MOCK env flag) — `is_mock` is never a
    parameter callers pass in; `_call_mock`/`_call_real` each hardcode
    their own literal at the point they write the log row, so there is no
    code path where a caller could set it wrong.
  - Persistent cache (`llm_response_cache` table), Reviewer and Developer
    only (Phase 3): keyed by (agent_name, wcag_rule, normalized
    html_snippet). Developer's cache-hit path always overrides the cached
    `target_selector` with the current violation's own `element_selector`
    rather than trusting the cached value — `target_selector` is a verbatim
    copy of input, not independently generated content, so this fully
    neutralizes the only real risk of caching it. Not used for Impact: its
    LLM-fallback reasons about the page URL, not the violating element, so
    the html_snippet-keyed cache shape doesn't semantically apply to it.
  - per-call model override (`model` param) — Phase 3 cost optimization
    routes Impact's LLM-fallback calls to IMPACT_FALLBACK_MODEL_NAME
    (smaller/cheaper than MODEL_NAME); Reviewer/Developer stay on MODEL_NAME
    since those steps are fix-quality-critical.
  - every call logged to llm_call_logs (latency/tokens/model/cache_hit/
    is_mock/error/error_type), success or failure — CLAUDE.md's
    instrumentation rule is not optional, including failed calls.
    `model_used` always reflects the actual resolved model for that call.

Default model: qwen/qwen3-32b via Groq's free tier. Groq's strict, schema-
guaranteed structured-output mode is only available on gpt-oss-20b/120b,
not this model — so this client uses non-strict `{"type": "json_object"}`
(guarantees valid JSON syntax, not schema conformance) plus real Pydantic
validation. A validation failure is a real, expected, and fully-handled
failure mode here, not a bug.

Full design reasoning (model choice, structured-output tradeoff, cache
scoping/normalization, error-handling contract) is logged in
C:\\Users\\siddh\\.claude\\plans\\delegated-sniffing-lollipop.md.

**Rate-limit pacing (added after Phase 2's own verification):** a real
scan hit repeated Groq 429s almost immediately once run against a
violation-heavy real page. Groq's actual binding constraint for this
account is 6,000 tokens/minute per model (`x-ratelimit-limit-tokens`), not
the RPM figure the model choice was originally reasoned about — at ~650
tokens/real-call that's only ~9 sustainable calls/minute on qwen3-32b.
`_call_real` tracks each model's real remaining-token budget from Groq's
own response headers and adaptively sleeps only when that specific model's
budget is actually low, rather than pacing every call with a fixed delay.
Confirmed live (Phase 3, 2026-07-09) that qwen/qwen3-32b and
llama-3.1-8b-instant carry fully independent rate-limit budgets — hence
`_remaining_tokens`/`_reset_at_monotonic` are dicts keyed by resolved model
name, not single account-wide values. See design.md's rate-limit-pacing
subsection (next to Section 7) for the full reasoning, including why this
was fixed immediately rather than folded into Phase 3's cost-optimization
scope (that's about making fewer calls; this is about not exceeding the
rate of calls made).
"""
import asyncio
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from agents.developer.schema import DeveloperOutput
from agents.impact.schema import ImpactOutput
from agents.reviewer.schema import ReviewerOutput
from config import settings
from db import async_session_factory
from models import AgentName, LlmCallLog, LlmResponseCache

logger = logging.getLogger("accessibility_agent.llm_client")

MODEL_NAME = "qwen/qwen3-32b"
# Phase 3 cost optimization: Impact's ambiguous-case LLM fallback (the
# critical-path URL heuristic already skips the LLM entirely for the
# clear-cut cases) is a coarser judgment than Developer's fix-generation, so
# it's routed to a smaller/cheaper model instead of MODEL_NAME. Verified
# live against Groq's real API (not just their docs) on 2026-07-09: returns
# HTTP 200 with its own independent rate-limit budget (14400 req/6000
# tokens, vs. qwen3-32b's separate 1000 req/6000 tokens) — confirming both
# that the model name is currently valid and that Groq tracks rate limits
# per-model, not per-account (see the per-model _remaining_tokens/
# _reset_at_monotonic dicts below).
IMPACT_FALLBACK_MODEL_NAME = "llama-3.1-8b-instant"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
REQUEST_TIMEOUT_S = 30
# Raised from an initial 1000 after live verification: Developer calls
# were observed up to 1362 tokens (Reviewer/Impact stay lower, ~400-980),
# so 1000 wasn't comfortable headroom after all — it let some calls fire
# with just enough reported "remaining" budget to look safe but not
# enough to actually cover a longer Developer response, causing residual
# 429s. 1500 clears the observed max with real margin for variance.
TOKEN_SAFETY_MARGIN = 1500
# Closes a gap TOKEN_SAFETY_MARGIN alone doesn't: right after a per-minute
# window resets, several same-page calls can each individually clear the
# token-safety-margin check before any of their own cost is reflected in
# the next one, until the window's real budget is actually exhausted mid-
# burst (see eval/PHASE5_PASS1B_SESSION1_REPORT.md — 674/1365 real calls
# failed this way, concentrated on color-contrast's dense per-page bursts).
# A minimum floor between calls caps how many can stack up in that gap.
# Starting value, not live-tuned yet (TOKEN_SAFETY_MARGIN itself was
# initially 1000 and only raised to 1500 after real observed failures).
MIN_CALL_INTERVAL_S = 0.5
# Generous relative to the ~400-600 total tokens seen in real benchmark
# calls (see plan Context) — qwen3's hidden reasoning tokens still consume
# this budget even though reasoning_format="hidden" keeps them out of the
# visible `content`, so too tight a limit risks truncating the actual
# JSON answer after the hidden reasoning eats most of it.
MAX_TOKENS = 2048
# Text column, no real storage cost — err toward keeping the debugging-
# critical raw response rather than truncating it away (see plan: a fully
# wrong response could itself run close to MAX_TOKENS worth of characters).
ERROR_FIELD_MAX_CHARS = 8000

_http_client: httpx.AsyncClient | None = None

# Rate-limit pacing state — shared across every real call (and across
# concurrent scans in this process, see _rate_limit_lock below), since
# Groq's token budget is per-account *per-model* (confirmed live, Phase 3 —
# see IMPACT_FALLBACK_MODEL_NAME's comment above): each model has its own
# independent budget, so pacing state must be keyed by resolved model name,
# not a single shared value, once a second model is in play.
_rate_limit_lock = asyncio.Lock()
_remaining_tokens: dict[str, int] = {}
_reset_at_monotonic: dict[str, float] = {}
_last_call_at_monotonic: dict[str, float] = {}

# Module-local aliases so tests can fake time/sleep without monkeypatching
# the real global time/asyncio modules (see backend/tests/graph/
# test_llm_client_pacing.py).
_monotonic = time.monotonic
_sleep = asyncio.sleep


class LlmCallError(Exception):
    def __init__(self, message: str, error_type: str | None = None) -> None:
        super().__init__(message)
        self.error_type = error_type


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient()
    return _http_client


def _parse_reset_duration(value: str) -> float:
    """Parses Groq's Go-style duration strings (e.g. "3.84s", "12s",
    "1m30s", "7m12s") into seconds. Returns 0.0 for anything unrecognized
    rather than raising — a parse miss should degrade to "don't pace",
    not crash a real LLM call over a header-format surprise."""
    match = re.match(r"^(?:(\d+)m)?(\d+(?:\.\d+)?)s$", value.strip())
    if not match:
        return 0.0
    minutes = float(match.group(1)) if match.group(1) else 0.0
    seconds = float(match.group(2))
    return minutes * 60 + seconds


def _update_rate_limit_state(model: str, response: httpx.Response) -> None:
    """Reads Groq's real token-budget headers after every real call —
    success or 429, both carry them, and a 429's headers are in fact the
    most useful signal since they reflect the post-limit state directly.
    Keyed by model since Groq tracks the budget per-model (see
    IMPACT_FALLBACK_MODEL_NAME's comment)."""
    remaining = response.headers.get("x-ratelimit-remaining-tokens")
    reset = response.headers.get("x-ratelimit-reset-tokens")
    if remaining is not None:
        try:
            _remaining_tokens[model] = int(remaining)
        except ValueError:
            pass
    if reset is not None:
        _reset_at_monotonic[model] = _monotonic() + _parse_reset_duration(reset)


async def _wait_for_rate_limit_if_needed(model: str) -> None:
    """Adaptive pacing: only sleeps when that model's real remaining token
    budget is actually low. Runs calls back-to-back with zero delay
    whenever there's genuine headroom (including the very first call for a
    given model, when there's no prior observation yet)."""
    remaining = _remaining_tokens.get(model)
    reset_at = _reset_at_monotonic.get(model)
    if remaining is None or reset_at is None:
        return
    if remaining >= TOKEN_SAFETY_MARGIN:
        return
    wait_s = reset_at - _monotonic()
    if wait_s > 0:
        logger.info(
            "pacing: model=%s only %d tokens remaining (< %d safety margin), sleeping %.2fs for Groq's rate-limit window to reset",
            model, remaining, TOKEN_SAFETY_MARGIN, wait_s,
        )
        await _sleep(wait_s)


async def _wait_for_min_interval_if_needed(model: str) -> None:
    """Floor delay between any two consecutive real calls to the same
    model, regardless of reported remaining budget — layers on top of
    _wait_for_rate_limit_if_needed to prevent same-page bursts from
    stacking up faster than Groq's per-model counter can be trusted (see
    MIN_CALL_INTERVAL_S)."""
    last_call_at = _last_call_at_monotonic.get(model)
    if last_call_at is None:
        return
    remaining = MIN_CALL_INTERVAL_S - (_monotonic() - last_call_at)
    if remaining > 0:
        await _sleep(remaining)


async def _make_paced_request(model: str, payload: dict, headers: dict) -> tuple[httpx.Response, int]:
    """The only place that actually calls Groq. Wraps the pace-check, the
    real HTTP call, and the rate-limit-state update in a single lock so
    concurrent scans (this project already runs them via FastAPI
    BackgroundTasks — see Phase 1's documented no-shared-browser-pool
    limitation) can't race past each other's view of the shared per-model
    token budget. Serializing the network call itself costs nothing real:
    Groq's own ceiling already caps achievable throughput well below what
    local concurrency could otherwise attempt."""
    async with _rate_limit_lock:
        await _wait_for_rate_limit_if_needed(model)
        await _wait_for_min_interval_if_needed(model)
        start = time.monotonic()
        client = _get_http_client()
        response = await client.post(GROQ_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_S)
        latency_ms = int((time.monotonic() - start) * 1000)
        _update_rate_limit_state(model, response)
        _last_call_at_monotonic[model] = _monotonic()
        return response, latency_ms


def _mock_enabled() -> bool:
    # Read fresh every call (not cached at import time) so tests can toggle
    # LLM_MOCK without reimporting this module.
    return os.environ.get("LLM_MOCK", "false").strip().lower() == "true"


def _classify_error(e: Exception) -> str:
    if isinstance(e, httpx.TimeoutException):
        return "timeout"
    if isinstance(e, httpx.HTTPStatusError):
        return "rate_limited" if e.response.status_code == 429 else "http_error"
    if isinstance(e, json.JSONDecodeError):
        return "json_decode_error"
    if isinstance(e, ValidationError):
        return "validation_error"
    return "unknown"


def _extract_json(raw_content: str) -> str:
    """Defensive extraction for non-strict JSON mode: slice from the first
    '{' to the last '}' in case the model wraps its answer in markdown
    fences or adds prose despite being told not to. Still raises (as a
    JSONDecodeError, handled uniformly with every other failure mode) if
    no JSON object is present at all."""
    start = raw_content.find("{")
    end = raw_content.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise json.JSONDecodeError("no JSON object found in response", raw_content, 0)
    return raw_content[start:end + 1]


def _normalize_html(html_snippet: str) -> str:
    """Conservative, correctness-first normalization for the Reviewer cache
    key: collapse whitespace, lowercase tag/attribute names only — never
    attribute values or text content. Several of the 9 locked rules need
    real attribute values to reason correctly (color-contrast's inline
    colors, html-lang-valid's lang value distinguishing "missing" from
    "invalid"), so this deliberately has a lower cross-page hit rate in
    exchange for zero risk of conflating two different violations."""
    collapsed = re.sub(r"\s+", " ", html_snippet).strip()

    def _lower_opening_tag(match: re.Match) -> str:
        # Matches "<tagname ...rest-of-tag-up-to-'>'" (not including '>').
        inner = match.group(0)
        head, _, rest = inner.partition(" ")
        head = head.lower()
        if not rest:
            return head
        # Lowercase attribute names only (the identifier before each '='),
        # leaving attribute values untouched.
        rest = re.sub(r"([A-Za-z_-]+)(?==)", lambda m: m.group(1).lower(), rest)
        return f"{head} {rest}"

    return re.sub(r"</?[A-Za-z][^>]*", _lower_opening_tag, collapsed)


_CACHEABLE_AGENTS = (AgentName.Reviewer, AgentName.Developer)


def _cache_key(agent_name: AgentName, wcag_rule: str, html_snippet: str) -> str:
    # Generalized from the original Reviewer-only literal
    # (f"Reviewer|{wcag_rule}|{normalized}") — 100% backward-compatible with
    # every existing cached row, since AgentName.Reviewer.value == "Reviewer".
    normalized = _normalize_html(html_snippet)
    raw = f"{agent_name.value}|{wcag_rule}|{normalized}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _write_log(
    *, agent_name: AgentName, latency_ms: int, tokens_used: int, model_used: str,
    cache_hit: bool, is_mock: bool, confidence_score: float | None,
    error: str | None = None, error_type: str | None = None,
) -> None:
    async with async_session_factory() as db:
        db.add(LlmCallLog(
            agent_name=agent_name, latency_ms=latency_ms, tokens_used=tokens_used,
            model_used=model_used, cache_hit=cache_hit, is_mock=is_mock,
            confidence_score=confidence_score, error=error, error_type=error_type,
            created_at=datetime.now(timezone.utc),
        ))
        await db.commit()


# Canned, schema-valid responses for LLM_MOCK=true — see _call_mock. Kept
# here (not in each agents/<name>/schema.py) so mock-response upkeep lives
# in one place alongside the mock dispatch logic that uses it.
_MOCK_RESPONSES: dict[type[BaseModel], dict] = {
    ReviewerOutput: {
        "confirmed": True, "confidence_score": 0.9,
        "reasoning": "Mock response (LLM_MOCK=true) — not a real model judgment.",
    },
    ImpactOutput: {
        "is_critical_path": False, "business_risk_score": 0.3,
        "reasoning_text": "Mock response (LLM_MOCK=true) — not a real model judgment.",
    },
    DeveloperOutput: {
        "proposed_code_diff": "<!-- mock fix (LLM_MOCK=true) -->",
        "target_selector": "mock-selector",
    },
}


async def call_llm(
    agent_name: AgentName,
    wcag_rule: str,
    html_snippet: str | None,
    system_prompt: str,
    user_prompt: str,
    schema: type[BaseModel],
    element_selector: str | None = None,
    model: str | None = None,
) -> BaseModel:
    """Single entry point every node calls. `html_snippet` is only used for
    the cache key (Reviewer and Developer — see module docstring); other
    agents may pass None since it's unused for them. `element_selector` is
    only used for Developer's cache-hit safety override (see _call_real).
    `model` overrides MODEL_NAME for this call (Impact's cost-optimization
    routing); omit to use the default."""
    if _mock_enabled():
        return await _call_mock(agent_name, schema, model)
    return await _call_real(
        agent_name, wcag_rule, html_snippet, system_prompt, user_prompt, schema,
        element_selector, model,
    )


async def _call_mock(
    agent_name: AgentName, schema: type[BaseModel], model: str | None = None,
) -> BaseModel:
    example = _MOCK_RESPONSES.get(schema)
    if example is None:
        raise LlmCallError(f"no mock response registered for schema {schema.__name__}")
    result = schema.model_validate(example)
    await _write_log(
        agent_name=agent_name, latency_ms=0, tokens_used=0, model_used=model or MODEL_NAME,
        cache_hit=False, is_mock=True,
        confidence_score=getattr(result, "confidence_score", None),
    )
    return result


async def _call_real(
    agent_name: AgentName,
    wcag_rule: str,
    html_snippet: str | None,
    system_prompt: str,
    user_prompt: str,
    schema: type[BaseModel],
    element_selector: str | None = None,
    model: str | None = None,
) -> BaseModel:
    resolved_model = model or MODEL_NAME
    cache_key = None
    if agent_name in _CACHEABLE_AGENTS and html_snippet is not None:
        cache_key = _cache_key(agent_name, wcag_rule, html_snippet)
        async with async_session_factory() as db:
            cached = (await db.execute(
                select(LlmResponseCache).where(LlmResponseCache.cache_key == cache_key)
            )).scalar_one_or_none()
        if cached is not None:
            result = schema.model_validate(json.loads(cached.response_json))
            if agent_name == AgentName.Developer and element_selector is not None:
                # Safety override: target_selector is not independently
                # generated content — the Developer prompt tells the LLM to
                # copy element_selector verbatim — so always trust the
                # CURRENT violation's own selector on a cache hit, never the
                # cached value.
                result = result.model_copy(update={"target_selector": element_selector})
            await _write_log(
                agent_name=agent_name, latency_ms=0, tokens_used=0, model_used=resolved_model,
                cache_hit=True, is_mock=False,
                confidence_score=getattr(result, "confidence_score", None),
            )
            return result

    payload = {
        "model": resolved_model,
        "temperature": 0.2,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if resolved_model == MODEL_NAME:
        # `reasoning_format` is a qwen3-specific param (suppresses hidden
        # chain-of-thought tokens from `content`) — confirmed live (Phase 3)
        # that Groq rejects it outright with a 400 for non-reasoning models
        # like IMPACT_FALLBACK_MODEL_NAME, so it's only sent for MODEL_NAME.
        payload["reasoning_format"] = "hidden"
    headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}", "Content-Type": "application/json"}

    start = time.monotonic()
    tokens_used = 0
    raw_content = ""
    try:
        response, latency_ms = await _make_paced_request(resolved_model, payload, headers)
        response.raise_for_status()
        data = response.json()
        tokens_used = data.get("usage", {}).get("total_tokens", 0)
        raw_content = data["choices"][0]["message"]["content"]
        parsed = json.loads(_extract_json(raw_content))
        result = schema.model_validate(parsed)
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        error_type = _classify_error(e)
        await _write_log(
            agent_name=agent_name, latency_ms=latency_ms, tokens_used=tokens_used,
            model_used=resolved_model, cache_hit=False, is_mock=False, confidence_score=None,
            error_type=error_type,
            error=f"{type(e).__name__}: {e}\n--- raw response ---\n{raw_content}"[:ERROR_FIELD_MAX_CHARS],
        )
        raise LlmCallError(f"{agent_name.value} call failed: {e}", error_type=error_type) from e

    await _write_log(
        agent_name=agent_name, latency_ms=latency_ms, tokens_used=tokens_used,
        model_used=resolved_model, cache_hit=False, is_mock=False,
        confidence_score=getattr(result, "confidence_score", None),
        error=None, error_type=None,
    )

    if cache_key is not None:
        async with async_session_factory() as db:
            db.add(LlmResponseCache(
                wcag_rule=wcag_rule, cache_key=cache_key,
                response_json=result.model_dump_json(),
                created_at=datetime.now(timezone.utc),
            ))
            try:
                await db.commit()
            except Exception:
                # Unique-index race: another concurrent call already cached
                # this exact key. The real LLM call above already succeeded
                # and was logged — nothing to retry, just don't double-insert.
                await db.rollback()

    return result
