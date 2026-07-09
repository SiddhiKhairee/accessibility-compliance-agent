# Phase 3 Completion Report — Fix Verification + Cost Optimization

Verifier is real end-to-end (no LangGraph restructuring — still exactly 4
nodes), and two real cost-optimization levers are live: Developer caching
and Impact model routing. Every number in this report was queried directly
from `llm_call_logs`/`fixes` on the real dev DB, or produced by a live call
against the real Groq API — none are estimated, per CLAUDE.md's rule.

## 1. What was built

| Component | What changed |
|---|---|
| `backend/app/verifier.py` (new) | `verify_fix()`: pre-apply `html.parser` tag-balance sanity check, real Playwright page load, outerHTML replacement at `target_selector`, full `detect_violations()` rerun, diff against the page's pre-fix baseline. Own Playwright lifecycle, no DB access — same flat-module convention as `detector.py`/`crawler.py`. |
| `graph.py`'s `verifier_node` | Calls `verify_fix()` once; on any non-`verified` outcome, one mechanical retry (same `proposed_code_diff`, fresh page load, no new Developer LLM call); the retry's own outcome is always authoritative. Maps to `verified`/`rejected`/`manual_review` + `FixFailureReason`. Graph topology untouched — 4 nodes, linear edges. |
| `agents/verifier/schema.py` | `VerifierOutput` replaced (`status: str` stub) with `verification_status: FixVerificationStatus`, `failure_reason: FixFailureReason | None`, `retry_count: int`. |
| `main.py`'s `run_scan` | Threads each page's baseline violation set (`{wcag_rule, element_selector}` pairs, built from data already in memory — no new DB query) into `ReasoningState`; writes the real `verifier_result` into each `Fix` row instead of the old hardcoded `verification_status=None, retry_count=0`. `verified_at` stamps on any terminal verdict, not only `verified`. |
| `llm_client.py` | Cache key generalized to `(agent_name, wcag_rule, html_snippet)` — Developer is now cacheable; a cache hit always overrides `target_selector` with the *current* call's `element_selector`, never the cached value. `call_llm`/`_call_real`/`_call_mock` gained a `model` override param; `_write_log`'s `model_used` reflects the real resolved model on every path. New `IMPACT_FALLBACK_MODEL_NAME = "llama-3.1-8b-instant"`, routed from `impact_node`'s LLM-fallback branch. |
| `backend/app/cost_report.py` (new) | `compute_agent_cost_summary()`: real query over `llm_call_logs`/`fixes` — per-agent call count/avg tokens/cache-hit rate/models used, `fixes.verification_status` distribution, retry rate. Plain importable function + CLI entry point, reusable by Phase 4's dashboard. |

**Confirmed design decisions** (settled with the user before implementation, not re-litigated here): `rejected` = clean technical run, violation persists/new one appeared, `failure_reason=None`; `manual_review` = a technical failure that persisted through the retry, `failure_reason` set; on a mixed first-attempt-vs-retry outcome, the retry's own result always wins; `verified_at` stamps on any terminal verdict.

## 2. Live verification — Developer cache-hit + `target_selector` override (real Groq, real dev DB)

The one real risk this caching change introduces is a stale `target_selector` leaking from a different violation's cached response. Directly tested against real Groq, not mocked:

```
Call 1: element_selector='selector-A' -> real Groq call
  result1.target_selector = 'selector-A'
  result1.proposed_code_diff = '<img src="live-cache-check.jpg" alt="Description of image">'

Call 2: SAME wcag_rule/html_snippet, element_selector='selector-B'
  result2.target_selector = 'selector-B'
  result2.proposed_code_diff = '<img src="live-cache-check.jpg" alt="Description of image">'  (identical — reused from cache)

llm_call_logs (most recent first):
  id=522 agent=Developer model_used=qwen/qwen3-32b tokens_used=0   cache_hit=True
  id=521 agent=Developer model_used=qwen/qwen3-32b tokens_used=402 cache_hit=False
```

Call 2 was a genuine cache hit (`tokens_used=0`, no network call) **and** correctly returned `target_selector='selector-B'`, not the cached `'selector-A'` — the override works, not just the caching trigger.

## 3. Live verification — Impact model routing (real Groq, real dev DB)

```
impact_node() called with a non-critical-path URL (https://example.com/gallery/photos)
  impact_result.is_critical_path = False   (confirms the LLM-fallback branch ran, not the URL heuristic)

Most recent Impact llm_call_logs row:
  id=523 agent=Impact model_used=llama-3.1-8b-instant tokens_used=311 cache_hit=False is_mock=False
```

`model_used == IMPACT_FALLBACK_MODEL_NAME`: confirmed directly from the logged row, not inferred.

## 4. Two real bugs found only by testing against the live Groq API (not mocked tests)

**Bug 1 — `reasoning_format: "hidden"` is qwen3-specific, not a general Groq param.** A real scan's Impact call failed with a **hard 400**: `` `reasoning_format` is not supported with this model ``, reproduced directly via `curl` against Groq's real API. `_call_real`'s payload now only includes `reasoning_format` when `resolved_model == MODEL_NAME`. Verified by capturing the actual outgoing payload (not just success/failure) on a real call for each model:

```
payload 0: model='qwen/qwen3-32b'         'reasoning_format' in payload=True  (value='hidden')
payload 1: model='llama-3.1-8b-instant'   'reasoning_format' in payload=False (value=None)
```

Both calls succeeded. The fix is correctly conditional — not accidentally dropped for qwen3-32b.

**Bug 2 — Groq rate limits are tracked per-model, not per-account.** Confirmed live: a same-second probe showed `qwen/qwen3-32b` at a 1000 req / 6000 token budget and `llama-3.1-8b-instant` at a separate 14400 req / 6000 token budget, decrementing independently. `_remaining_tokens`/`_reset_at_monotonic` changed from single globals to `dict[str, ...]` keyed by resolved model name.

**Regression check on qwen3-32b's already-verified Phase 2 pacing behavior**, after the dict refactor — 6 back-to-back real Reviewer calls (unique `wcag_rule` per call, so none hit the cache):

```
successes=6 failures=0
_remaining_tokens after run: {'qwen/qwen3-32b': 5218}
llm_call_logs (6 rows): tokens_used = 516, 486, 469, 443, 542, 473 — all error_type=None
```

Zero unexpected failures, zero `rate_limited` rows, state correctly keyed by `'qwen/qwen3-32b'` — the per-model refactor did not regress Phase 2's pacing.

## 5. Real cost/verification numbers (`cost_report.py`, live dev DB — not a mocked run)

```json
{
  "by_agent": {
    "Reviewer":  {"call_count": 188, "avg_tokens_per_call": 137.5, "cache_hit_rate": 0.356, "models_used": ["qwen/qwen3-32b"]},
    "Impact":    {"call_count": 103, "avg_tokens_per_call": 513.4, "cache_hit_rate": 0.0,   "models_used": ["llama-3.1-8b-instant", "qwen/qwen3-32b"]},
    "Developer": {"call_count": 96,  "avg_tokens_per_call": 716.4, "cache_hit_rate": 0.0104, "models_used": ["qwen/qwen3-32b"]}
  },
  "fix_verification_status_counts": {"unset": 128, "verified": 1},
  "fix_retry_rate": 0.0,
  "total_fixes": 129
}
```

**Read honestly, not at face value:**
- This is **cumulative dev-DB history since Phase 2**, not an isolated Phase-3-only benchmark or a controlled before/after A/B run. The 128 "unset" `fixes` rows predate Phase 3 entirely (created before `verification_status` was ever written) — they are not 128 Phase-3 verification failures, they're old rows from before this phase's write path existed.
- Developer's `cache_hit_rate = 1/96 = 0.0104` is **exactly** the one live cache-hit test run in Section 2 above — internally consistent, not a coincidence, and confirms Developer caching had never fired before this session (correct, since it didn't exist before Phase 3).
- Impact's `cache_hit_rate = 0.0` is correct by design, not a bug — Impact was never cached, on purpose (its LLM-fallback reasons about page URL, not the violating element, a different key shape). `models_used` shows both `qwen/qwen3-32b` and `llama-3.1-8b-instant` because it reflects history straddling the mid-session model-routing change, not two models used concurrently today.
- `fix_retry_rate = 0.0` is expected: the only real Fix with a populated `verification_status` (the one end-to-end `verified` run in Section 6 below) verified on its first attempt, so `retry_count=0`; no real retry path has fired yet in production use.
- A controlled before/after benchmark (same site, pre- vs. post-Phase-3 code, isolated from historical noise) would be needed for a resume-quality "X% cost reduction" claim. That wasn't required to close this phase's own checkboxes (which only require the numbers be real and logged, not a specific magnitude) — flagging it here as a reasonable next step, not overclaiming what today's numbers show.

## 6. Full end-to-end real-Groq scan (not `LLM_MOCK`)

Ran one real scan (`POST`-equivalent via `run_scan()` directly) against a local `missing_alt.html` page:

- Developer proposed a real fix via real Groq.
- Verifier applied it via real Playwright `outerHTML` replacement, reran the real detector, and confirmed the violation was gone with nothing new introduced.
- Resulting `Fix` row: `verification_status=FixVerificationStatus.verified, failure_reason=None, retry_count=0, verified_at=2026-07-09 22:27:40.752841+00:00`.

## 7. Test results

- **52/52 pytest tests pass** (42 prior − 1 removed stub test `test_verifier_is_structural_stub` + 10 new tests in `backend/tests/verifier/test_verifier.py` + 1 new `test_developer_cache_hit_overrides_target_selector`).
- New verifier tests cover: verified (clean fix), rejected (violation persists), rejected (new violation introduced), `dom_changed`, `invalid_html` (caught pre-Playwright), `playwright_timeout` (via the existing `/slow` fixture endpoint), `diff_failed_to_apply` (monkeypatched — real browsers rarely reject `outerHTML` assignment organically), the mechanical retry path (`retry_count == 1`), and a `needs_review`-baseline case (reusing `duplicate_id_aria.html`) proving the diff logic treats `needs_review` and `confirmed` identically.
- Every new test's fixture behavior was run live against real Playwright/axe-core before being trusted (e.g. confirmed live that `document.documentElement.outerHTML` replacement throws `NoModificationAllowedError`, ruling out `html`-selector-based fixes as a viable test case and steering the `needs_review` test toward `duplicate_id_aria.html`'s `span:nth-child(2)` target instead).
- `ruff check backend/`: clean.
- Existing tests updated for the new reality, not just patched to pass: `test_full_graph_sequence_llm_mock`'s mocked Developer response (`target_selector="mock-selector"`, `proposed_code_diff="<!-- mock fix -->"`) now deterministically produces `manual_review`/`invalid_html` (an HTML comment has no real tags, correctly caught by the pre-apply sanity check) rather than the old stub's `pending_verification`; all `_make_paced_request`/`_call_mock` monkeypatch signatures across the cache/error-logging test files updated for the new `model` parameter.

## 8. Known limitations carried forward (documented, not silently fixed)

- **`invalid_html` detection is necessarily partial.** The stdlib `html.parser`-based tag-balance check catches gross/truncated breakage (its main real-world target: a truncated LLM response) but not most things a human would call invalid HTML — real browsers repair almost everything silently. No HTML validation library exists in `requirements.txt`, and none was added for this.
- **axe selector drift is a known, undecided risk.** `nth-child`-style selectors for *unrelated* elements can shift after a DOM mutation, which could in principle cause a rare false-positive `new_violation` verdict unrelated to the actual fix. Not addressed in Phase 3 (would need stable DOM identity tracking); documented as a limitation for Phase 5's evaluation to surface if it's a real problem in practice, not assumed away.
- **`needs_review` vs `confirmed` are diffed identically by design**, not by oversight — the Verifier's job is confirming the violation is gone, not re-litigating axe's own detection confidence. Reviewer/Impact/Developer still don't use `detection_confidence` for extra scrutiny (unchanged from Phase 2.6's original deferral).
- **Today's cost numbers (Section 5) are cumulative history, not an isolated benchmark** — see the honest caveats there.

## 9. Remote CI verification (not just local pytest)

Local 52/52 is not treated as sufficient on its own, per this project's own Phase 2.5 CI/branch-protection standard. Pushed `phase-3-fix-verification` and opened PR #16 into `main`:

- **Push-triggered run**: [`29055775871`](https://github.com/SiddhiKhairee/accessibility-compliance-agent/actions/runs/29055775871) — `conclusion: success`, all steps green (lint, Playwright install, both Alembic migration checks, full pytest suite), 2m18s.
- **PR-triggered run**: [`29055787660`](https://github.com/SiddhiKhairee/accessibility-compliance-agent/actions/runs/29055787660) — `conclusion: success`.
- **PR #16 merge readiness**: `mergeStateStatus: "CLEAN"`, `mergeable: "MERGEABLE"`, both `test` status checks report `SUCCESS`.
- **Branch protection on `main`** (confirmed via `gh api .../branches/main/protection`, not assumed carried over from Phase 2.5): `required_status_checks.contexts: ["test"]`, `strict: true`, `enforce_admins: true`, `allow_force_pushes: false`, `allow_deletions: false` — the real gate that must pass before merge is in place and satisfied.
- PR not merged — merging is the user's call, not made here.

## 10. Real final state

- 52/52 pytest tests passing locally, `ruff check backend/` clean.
- Remote CI green on both the push and PR triggers for `phase-3-fix-verification` (PR #16), branch protection's required `test` check satisfied.
- One real, non-mocked, end-to-end `verified` Fix produced against real Groq + real Playwright + real axe-core.
- Two real bugs found by live verification (not assumed away by mocked tests), both fixed and regression-checked live.
- Phase 3 checkboxes closed in PLAN.md, with a full session-log entry; `docs/schema.md` and `design.md` updated to describe the real behavior, not the Phase 2 stub.
