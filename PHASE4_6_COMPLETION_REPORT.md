# Phase 4.6 Completion Report — Crawler bot-blocking / status-code detection

Closes the gap found while scoping Phase 5: `page.goto()` doesn't raise on
4xx/5xx HTTP responses, so a bot-blocked or CAPTCHA-challenged page was
being silently recorded as `status="loaded"` and scanned by axe-core as if
it were real content. `design.md` (Section 4b) already claimed 403 was
handled by the failed-page path before this phase; it wasn't, in code.

## 1. What was built

| Component | What changed |
|---|---|
| `backend/app/crawler.py` | `crawl_site()` now captures `page.goto()`'s return value. Explicit `response.status in BLOCKED_STATUS_CODES` check (`{403, 429, 503}`) routes into the existing failed/skip path with `failure_reason="blocked (status N)"`. A best-effort `CHALLENGE_MARKERS` substring sniff against the rendered HTML catches common 200-status CAPTCHA/Cloudflare-interstitial pages, with `failure_reason="blocked (challenge page detected)"`. Both paths skip snapshot write, detection, and link extraction — same as any other failed page. Module docstring updated to stop implying 403 was already handled. |
| `backend/tests/fixtures/server.py` | `_respond()` now takes a `status: int = 200` param (was hardcoded to 200). Added inline routes `/blocked_403`, `/blocked_429`, `/blocked_503` (real non-2xx responses) and `/challenge_page` (200 status, body containing challenge markers + a link to `page_a.html`, used to prove blocked pages don't get their links followed). |
| `backend/tests/crawler/test_crawler.py` | 5 new tests: one per status code, one for the challenge-page sniff, one proving a blocked/challenge page's links are never queued. 13/13 crawler tests passing (8 pre-existing + 5 new). |
| `design.md` Section 4b, `docs/schema.md` (`pages.failure_reason`) | Updated to describe the real mechanism (explicit status check + challenge sniff) instead of the previous inaccurate "(redirect, 403, etc.) handled the same as any failure" hand-wave. |
| `PLAN.md` Phase 4.6 | Checkboxes closed with real verification evidence inline (see Section 3 below). |

No DB migration: `pages.failure_reason` was already a free-text `Text`
column with no existing enum vocabulary (confirmed against
`Fix.failure_reason`/`FixFailureReason`, which *is* a real Postgres enum,
before assuming otherwise) — the `"blocked (...)"` prefix is enough to make
these entries greppable later without a schema change.

## 2. Scope decisions (made with you before implementing)

- **Status codes: exactly 403/429/503**, not a broader non-2xx sweep.
  404/500/etc. stay `"loaded"` — those are real app errors, not
  bot-blocking, and reclassifying them would have been a bigger, unasked-for
  behavior change.
- **User-Agent change: deferred, not built.** PLAN.md's own wording made
  this conditional on "real evidence" of fingerprint-based blocking showing
  up in testing. None did (Section 3) — the default headless Chromium UA
  loaded both test targets normally. Left unchecked in PLAN.md, not
  silently dropped.

## 3. Verification — real, not assumed

- **`pytest backend/tests/crawler/`: 13/13 passing.**
- **Full suite: `pytest backend/tests/`: 88/88 passing** — confirms
  `main.py`'s `status != "loaded"` checks, `PageOut` passthrough, and
  dashboard aggregation (all consume `status`/`failure_reason` as opaque
  strings already) needed no changes.
- **Real network round-trip**, per your explicit direction to use a
  synthetic public status-code endpoint rather than repeatedly probing a
  real anti-bot-protected site during dev iteration:
  - **httpstat.us was down at verification time** — real `curl -v` showed
    `schannel: server closed abruptly (missing close_notify)`, and the
    crawler itself reported `net::ERR_EMPTY_RESPONSE`, not a 403. Not a
    code bug — confirmed the service itself was unreachable, then switched
    to `httpbin.org`'s equivalent `/status/<code>` endpoints, which
    responded normally (`curl -o /dev/null -w '%{http_code}'` returned
    403/429/503 as expected).
  - `python crawler.py https://httpbin.org/status/403` → `[failed]
    depth=0 ... — blocked (status 403)`, `0/1 pages loaded successfully`,
    `0 violations`. Identical result for `/status/429` and `/status/503`
    (`blocked (status 429)` / `blocked (status 503)`).
  - Regression check: `https://httpbin.org/status/200` → `[loaded] ... 1
    violations`; `https://example.com` → `[loaded] ... 0 violations` — both
    still classified normally, confirming no false-positive reclassification
    of real pages.

## 4. Not done this phase, deliberately

- **User-Agent change** — deferred per Section 2, no evidence found to
  justify it.
- **No `CrawledPage`/DB schema change** — free-text `failure_reason` was
  sufficient; adding a status-code column or enum would have been scope
  beyond what this phase needed.
- **Challenge-page marker list is a heuristic, not exhaustive** —
  documented as such in `crawler.py` and `design.md`; will miss anti-bot
  pages using unrecognized copy. Not a gap to silently work around, per
  CLAUDE.md's documentation discipline for known limitations.
