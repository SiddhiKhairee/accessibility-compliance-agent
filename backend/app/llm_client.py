"""
llm_client.py — Groq API wrapper for the Phase 2 LangGraph reasoning layer.

Single entry point `call_llm()` used by all three real-LLM nodes (Reviewer,
Impact's ambiguous-URL fallback, Developer). Handles:
  - real-vs-mock dispatch (LLM_MOCK env flag) — `is_mock` is never a
    parameter callers pass in; `_call_mock`/`_call_real` each hardcode
    their own literal at the point they write the log row, so there is no
    code path where a caller could set it wrong.
  - Reviewer-only persistent cache (`llm_response_cache` table). Not used
    for Impact/Developer: Developer's output carries an instance-specific
    `target_selector` unsafe to reuse across two different violations;
    Impact's LLM-fallback reasons about the page URL, not the violating
    element, so this html_snippet-keyed cache doesn't semantically apply
    to it either. Both deferred to Phase 3's real cost-optimization scope.
  - every call logged to llm_call_logs (latency/tokens/model/cache_hit/
    is_mock/error/error_type), success or failure — CLAUDE.md's
    instrumentation rule is not optional, including failed calls.

Model: qwen/qwen3-32b via Groq's free tier. Groq's strict, schema-
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
account is 6,000 tokens/minute (`x-ratelimit-limit-tokens`), not the RPM
figure the model choice was originally reasoned about — at ~650
tokens/real-call that's only ~9 sustainable calls/minute. `_call_real`
now tracks the account's real remaining-token budget from Groq's own
response headers and adaptively sleeps only when that budget is actually
low, rather than pacing every call with a fixed delay. See design.md's
rate-limit-pacing subsection (next to Section 7) for the full reasoning,
including why this was fixed immediately rather than folded into Phase
3's cost-optimization scope (that's about making fewer calls; this is
about not exceeding the rate of calls made).
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
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
REQUEST_TIMEOUT_S = 30
# Raised from an initial 1000 after live verification: Developer calls
# were observed up to 1362 tokens (Reviewer/Impact stay lower, ~400-980),
# so 1000 wasn't comfortable headroom after all — it let some calls fire
# with just enough reported "remaining" budget to look safe but not
# enough to actually cover a longer Developer response, causing residual
# 429s. 1500 clears the observed max with real margin for variance.
TOKEN_SAFETY_MARGIN = 1500
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
# Groq's token budget is per-account, not per-call or per-scan.
_rate_limit_lock = asyncio.Lock()
_remaining_tokens: int | None = None
_reset_at_monotonic: float | None = None


class LlmCallError(Exception):
    pass


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


def _update_rate_limit_state(response: httpx.Response) -> None:
    """Reads Groq's real token-budget headers after every real call —
    success or 429, both carry them, and a 429's headers are in fact the
    most useful signal since they reflect the post-limit state directly."""
    global _remaining_tokens, _reset_at_monotonic
    remaining = response.headers.get("x-ratelimit-remaining-tokens")
    reset = response.headers.get("x-ratelimit-reset-tokens")
    if remaining is not None:
        try:
            _remaining_tokens = int(remaining)
        except ValueError:
            pass
    if reset is not None:
        _reset_at_monotonic = time.monotonic() + _parse_reset_duration(reset)


async def _wait_for_rate_limit_if_needed() -> None:
    """Adaptive pacing: only sleeps when the account's real remaining
    token budget is actually low. Runs calls back-to-back with zero delay
    whenever there's genuine headroom (including the very first call,
    when there's no prior observation yet)."""
    if _remaining_tokens is None or _reset_at_monotonic is None:
        return
    if _remaining_tokens >= TOKEN_SAFETY_MARGIN:
        return
    wait_s = _reset_at_monotonic - time.monotonic()
    if wait_s > 0:
        logger.info(
            "pacing: only %d tokens remaining (< %d safety margin), sleeping %.2fs for Groq's rate-limit window to reset",
            _remaining_tokens, TOKEN_SAFETY_MARGIN, wait_s,
        )
        await asyncio.sleep(wait_s)


async def _make_paced_request(payload: dict, headers: dict) -> tuple[httpx.Response, int]:
    """The only place that actually calls Groq. Wraps the pace-check, the
    real HTTP call, and the rate-limit-state update in a single lock so
    concurrent scans (this project already runs them via FastAPI
    BackgroundTasks — see Phase 1's documented no-shared-browser-pool
    limitation) can't race past each other's view of the shared
    per-account token budget. Serializing the network call itself costs
    nothing real: Groq's own ceiling already caps achievable throughput to
    ~9 calls/minute regardless of local concurrency."""
    async with _rate_limit_lock:
        await _wait_for_rate_limit_if_needed()
        start = time.monotonic()
        client = _get_http_client()
        response = await client.post(GROQ_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_S)
        latency_ms = int((time.monotonic() - start) * 1000)
        _update_rate_limit_state(response)
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


def _cache_key(wcag_rule: str, html_snippet: str) -> str:
    normalized = _normalize_html(html_snippet)
    raw = f"Reviewer|{wcag_rule}|{normalized}"
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
) -> BaseModel:
    """Single entry point every node calls. `html_snippet` is only used for
    the Reviewer-agent cache key (see module docstring) — pass the
    violation's real html_snippet for Reviewer calls; other agents may pass
    None since it's unused for them."""
    if _mock_enabled():
        return await _call_mock(agent_name, schema)
    return await _call_real(agent_name, wcag_rule, html_snippet, system_prompt, user_prompt, schema)


async def _call_mock(agent_name: AgentName, schema: type[BaseModel]) -> BaseModel:
    example = _MOCK_RESPONSES.get(schema)
    if example is None:
        raise LlmCallError(f"no mock response registered for schema {schema.__name__}")
    result = schema.model_validate(example)
    await _write_log(
        agent_name=agent_name, latency_ms=0, tokens_used=0, model_used=MODEL_NAME,
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
) -> BaseModel:
    cache_key = None
    if agent_name == AgentName.Reviewer and html_snippet is not None:
        cache_key = _cache_key(wcag_rule, html_snippet)
        async with async_session_factory() as db:
            cached = (await db.execute(
                select(LlmResponseCache).where(LlmResponseCache.cache_key == cache_key)
            )).scalar_one_or_none()
        if cached is not None:
            result = schema.model_validate(json.loads(cached.response_json))
            await _write_log(
                agent_name=agent_name, latency_ms=0, tokens_used=0, model_used=MODEL_NAME,
                cache_hit=True, is_mock=False,
                confidence_score=getattr(result, "confidence_score", None),
            )
            return result

    payload = {
        "model": MODEL_NAME,
        "temperature": 0.2,
        "max_tokens": MAX_TOKENS,
        "reasoning_format": "hidden",
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}", "Content-Type": "application/json"}

    start = time.monotonic()
    tokens_used = 0
    raw_content = ""
    try:
        response, latency_ms = await _make_paced_request(payload, headers)
        response.raise_for_status()
        data = response.json()
        tokens_used = data.get("usage", {}).get("total_tokens", 0)
        raw_content = data["choices"][0]["message"]["content"]
        parsed = json.loads(_extract_json(raw_content))
        result = schema.model_validate(parsed)
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        await _write_log(
            agent_name=agent_name, latency_ms=latency_ms, tokens_used=tokens_used,
            model_used=MODEL_NAME, cache_hit=False, is_mock=False, confidence_score=None,
            error_type=_classify_error(e),
            error=f"{type(e).__name__}: {e}\n--- raw response ---\n{raw_content}"[:ERROR_FIELD_MAX_CHARS],
        )
        raise LlmCallError(f"{agent_name.value} call failed: {e}") from e

    await _write_log(
        agent_name=agent_name, latency_ms=latency_ms, tokens_used=tokens_used,
        model_used=MODEL_NAME, cache_hit=False, is_mock=False,
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
