# Phase 5 — Pass 1b, Session 1 Report

**Date:** 2026-07-16 → 2026-07-17 (session spanned a UTC midnight rollover)
**Scope:** First real Reviewer-scoring run against the 30-site eval corpus (`eval/eval_corpus_30_sites.csv`), via `backend/app/eval_runner.py`. Pass 1a (crawl+detect) was already complete going in — this session exercised Pass 1b (real Groq Reviewer calls) for the first time.

## 1. Pre-run verification

- **Test suite:** `pytest backend/tests/` → **111 passed, 0 failed** (120s), against the real Docker Postgres test DB. Confirmed before any real spend.
- **Real Groq daily cap:** confirmed live via response headers on a real API call (console.groq.com/settings/limits needed a login this session didn't have) — **1000 requests/day, 6000 tokens/minute**, both per-model. Matches `EVAL_DAILY_CALL_CAP=1000`'s existing default exactly — no override was needed.

## 2. What happened, in order

1. **Run 1** — started clean (3,122 violations, all pending). Crashed after only **2** real Reviewer calls with `PermissionError: [WinError 5] Access is denied` on `os.replace()` inside `save_manifest()`. Root cause: `eval/` lives inside the OneDrive-synced `Desktop` folder, and OneDrive's sync client transiently locked `progress_pass1.json.tmp` right as the atomic rename tried to run.
   - Recovered manually: the `.tmp` file was a clean one-record superset of the committed manifest (confirmed by diffing `reviewer_status: "done"` counts in both files), so completing the stuck `os.replace()` by hand restored consistency with zero data loss.
2. User paused OneDrive sync. **Run 2** resumed and got much further (207 violations done total) before hitting the **identical** `WinError 5` again — proving OneDrive's pause alone didn't eliminate the lock (likely its filter driver, Windows Search indexing, or AV real-time scanning still touching the file). Recovered the same way.
3. **Fix applied:** added retry-with-backoff around the `os.replace()` call in `save_manifest()` (`backend/app/eval_runner.py`) — up to 5 attempts, 0.5s apart, re-raising only if every attempt fails. Verified with `pytest backend/tests/eval/` → **22 passed**, no regression.
4. **Run 3** — the fix worked: it hit the same transient lock once (`attempt 1/5`, logged as a `WARNING`, not a crash) and recovered automatically. Progressed to 678 done. This run was **stopped externally** (status `killed`, not a crash or budget stop) partway through; manifest was left in a fully consistent state (no stray `.tmp` file).
5. **Run 4 (resumed)** — ran to a clean **budget-gated stop** at exactly 900/1000 real calls for the (by-then-new) UTC day. This is where the large rate-limit failure spike (§3 below) occurred.

## 3. Real Groq calls: the wasted-call accounting

This is the part worth flagging clearly: **a large fraction of this session's real Groq spend did not produce a usable Reviewer result.**

### Session totals (all real, non-cached Reviewer calls to `qwen/qwen3-32b`, this session)

| Outcome | Count |
|---|---|
| **Success** | 685 |
| **Failed — `429 Too Many Requests`** | **680** |
| Cache hits (not counted against budget) | 390 |
| **Total real calls attempted** | **1,365** |

Roughly **50% of every real call this session hit a rate limit and produced nothing**, despite `llm_client.py` already having adaptive rate-limit pacing (it reads Groq's `x-ratelimit-remaining-tokens` header after each response and sleeps if a model's remaining budget drops below a 1,500-token safety margin).

### Where the failures actually concentrated

| UTC day | Success | Rate-limited |
|---|---|---|
| 2026-07-16 | 459 | 6 |
| 2026-07-17 | 226 | **674** |

The failure rate was **1.3%** on 2026-07-16 and **75%** on 2026-07-17 — nearly all of it landed in Run 4, and specifically on one WCAG rule:

| `wcag_rule` (manifest) | Failed count |
|---|---|
| `color-contrast` | 642 |
| `image-alt` | 27 |
| `link-name` | 5 |

### Root cause

`color-contrast` is typically both the most frequent violation per page *and* one of the larger `html_snippet` payloads sent to the Reviewer prompt, so a page with many consecutive color-contrast violations fires a burst of token-heavy calls back-to-back. The pacer in `llm_client.py` is **reactive**: it only knows a model's remaining token budget from the *previous* response's headers, and only sleeps if that already-stale number is low. Several calls can fire in quick succession showing "enough" headroom from stale readings before Groq's actual per-minute counter — updated server-side in real time — is exhausted, producing a run of 429s until the window resets. This is a real gap in the existing pacing design, not a one-off fluke: it's structural, and will recur on any run that hits a similarly violation-dense stretch of the corpus.

### A second, related bug found (not yet fixed)

The manifest recorded **all 674 of Run 4's failures as `error_type: "unknown"`**, not `rate_limited`. This traces to `eval_runner.py`'s exception handler:

```python
except Exception as e:
    v_entry["reviewer_status"] = "failed"
    v_entry["failure_reason"] = str(e)
    v_entry["error_type"] = llm_client._classify_error(e)
```

`e` here is the `LlmCallError` that `_call_real()` re-raises (`raise LlmCallError(...) from e`), not the original `httpx.HTTPStatusError`. `_classify_error()` only recognizes `httpx.TimeoutException`, `httpx.HTTPStatusError`, `json.JSONDecodeError`, and `ValidationError` by `isinstance` — a `LlmCallError` matches none of them, so it always falls through to `"unknown"`.

This did **not** corrupt the ground-truth data: `llm_client.py`'s own `_write_log()` classifies the *original* exception before it gets wrapped, so `llm_call_logs.error_type` in the database is correct (`rate_limited`, confirmed directly by query — see §3 table above). Only the **manifest's** per-violation `error_type` field is wrong. This matters because `eval_report.py`'s planned per-rule failure-rate calculation would read the manifest, not `llm_call_logs` — left as-is, it would have reported a misleading 95%-`color-contrast` "unknown failure" cluster instead of correctly attributing it to rate-limiting.

**This bug was found but deliberately not fixed this session**, per instruction to stop making code changes for today. It's an isolated one-line fix (pass the original exception to `_classify_error`, e.g. by not swallowing `__cause__`, or classifying before the `raise ... from e` wrap) for a future session.

## 4. Current corpus review state

Out of 3,122 total violations across the 30-site corpus:

| Status | Count |
|---|---|
| Reviewed (`done`) | 1,075 |
| Failed (`rate_limited`, mislabeled `unknown` in manifest) | 674 |
| Still pending | 1,373 |

Of the 1,075 completed reviews:
- `confirmed: true` — 761
- `confirmed: false` — 314
- `confidence_score` distribution: min 0.30, p25 0.60, median 0.75, p75 0.95, max 1.00, mean 0.758

## 5. Budget status / continuation

Run 4 stopped cleanly via the budget guard at **900/1000** real calls for 2026-07-17 (safety-margin threshold, 90% of cap) — a correct, expected stop, not a failure. Since that threshold was reached on the *current* UTC day, **there is no remaining budget until the next UTC midnight (2026-07-18 00:00 UTC)** — a same-day retry would immediately re-stop with zero progress, which is why none was attempted.

**This will need at least one more resumed session** to clear the remaining 1,373 pending violations (674 of which are re-attempts of calls that already failed once to rate-limiting, not new work). Given tonight's ~50% real-call failure rate, a straight resume tomorrow risks burning a similar share of the next day's budget on 429s again unless the pacing gap in §3 is addressed first — worth deciding on before the next real-spend session, not something to route around silently.

## 6. Recommendations for next session (not implemented today)

1. Fix the manifest-side error classification bug in `eval_runner.py` (§3) — small, isolated, no Pass 1a/detector/crawler impact.
2. Consider tightening `llm_client.py`'s rate-limit pacing to be less reactive under bursty same-rule call sequences — e.g., a small fixed inter-call floor delay, or treating a run of same-model calls within one page as a batch to pace proactively rather than per-call. Needs discussion before changing, since it affects the core call path used by production scans too, not just eval.
3. Consider moving `eval/progress_pass1.json` (and/or the whole repo) outside the OneDrive-synced path, or at minimum keeping the OneDrive-pause + retry-with-backoff combination in place for future long runs.
