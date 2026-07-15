# PLAN.md — Accessibility Compliance Agent

Resume point: work top to bottom. Don't start a phase until the previous
phase's deliverable is checked off and verified.

## Phase 0 — Design & Scoping
- [x] Lock v1 WCAG rule set — 9 rules, all fully automated via axe-core, no manual-judgment rules:
  1. Non-text Content (1.1.1) - image-alt, input-image-alt
  2. Contrast Minimum (1.4.3) - color-contrast
  3. Name/Role/Value forms (4.1.2) - label, button-name, aria-input-field-name
  4. Keyboard (2.1.1) - tabindex checks, keyboard traps
  5. Language of Page (3.1.1) - html-has-lang, html-lang-valid
  6. Bypass Blocks (2.4.1) - bypass, skip-link
  7. Duplicate ARIA/label IDs (4.1.2) - duplicate-id-aria
  8. Info and Relationships, structural only (1.3.1) - list, listitem, definition-list
  9. Link Purpose, presence only not quality (2.4.4) - link-name
- [x] Define "critical path" criteria for the Impact Agent: any page representing a
      required step in a core user task (transacting, authenticating, searching, or
      primary navigation), rather than supplementary content. V1 concrete instances:
      - Checkout / payment flows
      - Login / auth flows
      - Primary forms (signup, contact, etc.)
      - Search (/search or equivalent)
      - Primary navigation / header
- [x] Draft design.md v0 with architecture diagram
- [x] **Deliverable:** design.md draft + locked scope

## Phase 1 — Detection Engine + Non-Blocking API
- [x] Playwright crawler + axe-core detector
- [x] FastAPI endpoint returns scan_id immediately, runs crawl/detect via BackgroundTasks
- [x] GET /scan/{id} status endpoint for polling
- [x] Document BackgroundTasks limitation in design.md
- [x] Defensive crawling: timeouts, skip+log failures, exclude authenticated pages
- [x] **Deliverable:** API that accepts a URL, scans async, returns structured violations
- [x] **Verify:** run against 2-3 real public URLs, confirm structured output

## Phase 2 — Multi-Agent Reasoning Layer
- [x] LangGraph workflow, exactly 4 nodes:
  - [x] Reviewer Agent — confirms WCAG rule, confidence score
  - [x] Impact Agent — URL-pattern heuristics first (/checkout /cart /login /payment), LLM only for ambiguous cases
  - [x] Developer Agent — generates fix anchored to exact target CSS selector
  - [ ] Verifier Agent — see Phase 3 *(Phase 2 ships a structural stub only — no LLM call, no DOM re-check, returns `status="pending_verification"` — real logic is Phase 3's, graph topology already accommodates it)*
- [x] Every agent call logs latency_ms, tokens_used, model_used, cache_hit (+confidence_score for Reviewer) *(+ is_mock/error/error_type added this phase — see design.md Section 8)*
- [x] **Deliverable:** violations carry WCAG confirmation, impact score+reasoning, proposed fix
- [x] **Verify:** subagent review — confirm exactly 4 nodes, no scope creep *(confirmed: exactly 4 `add_node` calls, linear edges, no hidden subgraph, clean responsibility boundaries, no unnecessary abstraction — full report in session log)*

## Phase 2.5 — Automated Test Suite + CI/CD Pipeline
- [x] 2.5a — Test infrastructure: pytest + pytest-asyncio; separate test
      Postgres (docker-compose override or distinct port — never point
      tests at the real dev DB); Alembic migrations run against the test DB
      via fixture setup; `.env.test` with `LLM_MOCK=true` forced (no real
      Groq key needed in CI) *(built as a profile-gated `postgres_test`
      service in the existing docker-compose.yml, port 5434, distinct
      `accessibility_agent_test` DB — not an override file, since
      docker-compose.override.yml is already gitignored and wouldn't be
      shared; session-scoped autouse pytest fixture runs the real Alembic
      chain via a one-line conditional guard added to migrations/env.py so
      a caller-set sqlalchemy.url isn't clobbered back to dev — see
      design.md Section 10)*
- [x] 2.5b — Phase 1 regression tests: detector unit tests against static
      fixture HTML with known, hand-verified violations (not live sites);
      crawler tests (same-domain restriction, max_pages/max_depth capping,
      skip+log-on-failure) against a local test server, not the real
      internet; API layer POST /scan → GET /scan/{id} round-trip against
      test DB
- [x] 2.5c — Phase 2 regression tests: graph/node sequence in LLM_MOCK mode
      (Reviewer → Impact → Developer → Verifier); force a mock failure
      mid-graph, assert zero rows land in impact_assessments/fixes (the
      "no partial state" guarantee); cache_hit=true on repeated identical
      normalized input, plus explicit cases for normalization behavior
      (whitespace/tag-case only, never attribute values); is_mock/error_type
      logging — every call path writes a row, including failure paths
- [x] 2.5d — CI/CD: `.github/workflows/ci.yml` — Postgres service
      container, Alembic upgrade, lint (ruff/black), pytest, on every push;
      CI green is the gate before Phase 3 work begins
- [x] 2.5e — Verify & close: confirm the suite actually fails on an
      intentionally reintroduced bug (e.g. the datetime tz bug from Phase 1)
      — a suite that can't fail proves nothing; update CLAUDE.md/PLAN.md/
      design.md to reflect what was actually built
- [x] **Deliverable:** a real pytest suite covering Phase 1+2 regressions,
      running in CI on every push, gating Phase 3
- [x] **Verify:** CI is green on a clean run, and red when an intentional
      regression is reintroduced *(PR #12: run 28920503993 red — 12
      failed/29 passed, real datetime-tz regression — then run
      28920679468 green — 41 passed, after a confirmed byte-clean revert)*

**Note:** `.github/workflows/ci.yml` as built in Phase 2.5 covers
**backend only** — lint (ruff) + the full pytest suite against
`backend/`. No frontend code exists yet (confirmed during 2.5d), so no
frontend lint/test/CI was built. Do not assume the current CI gate covers
the whole project once the frontend ships in Phase 4 — see Phase 4.5.

## Phase 2.6 — Detector `reviewOnFail` Gap (backlog, found during 2.5b)
- [x] Audit all 9 locked v1 rules (not just `bypass`/`duplicate-id-aria`)
      for `reviewOnFail: true` in axe-core's rule metadata — confirm
      whether any other locked rules share this gap, since only 2 were
      found so far by accident (fixture verification), not via a full audit
      *(confirmed live: only `bypass`/`duplicate-id-aria`, of all 16 rule
      IDs across the 9 locked rules, are `reviewOnFail: true`)*
- [x] Decide how `incomplete`-array results should be handled for
      `reviewOnFail` rules — e.g. read `incomplete` for just the affected
      rules, treat them differently from violations (confidence caveat),
      or some other explicit decision — write the decision and reasoning
      into design.md before implementing *(read `incomplete` scoped to
      just these 2 rule IDs, tag results `detection_confidence=
      "needs_review"` vs `"confirmed"` — decision + reasoning in design.md
      Section 3)*
- [x] Implement the decided approach in detector.py
- [x] Update/add fixture tests in backend/tests/detector/test_detector.py
      to reflect the new behavior (the existing known-gap tests will need
      to change from "asserts absence" to "asserts presence" if the gap
      gets closed)
- [x] Re-verify: `bypass` and `duplicate-id-aria` fixtures that previously
      asserted absence now correctly surface, with no regressions on the
      other 7 rules' existing passing tests
- [x] **Deliverable:** detector.py reliably surfaces all 9 locked rules, or
      an explicit, documented reason why any specific rule still can't
- [x] **Verify:** full 2.5b test suite still green, plus new assertions for
      the previously-gapped rules *(42 passed — 41 prior + 1 net new: 2
      tests flipped, 1 added)*

## Phase 3 — Fix Verification + Cost Optimization
**Note:** Phase 3 verification logic should account for Phase 2.6's
detector `reviewOnFail` findings (see Phase 2.6) before assuming all 9
locked rules are reachable via `detect_violations()`.
- [x] Verification Agent applies fix locally at target selector, re-runs FULL detector
- [x] Diff entire before/after violation set (not just the one flagged rule)
- [x] Retry-once-then-manual_review logic with failure_reason enum
- [x] Real cost optimization: cache repeated identical violation patterns, and/or route simple steps to smaller model
- [x] Measure and log real before/after cost comparison
- [x] **Deliverable:** verified/rejected/manual_review fixes with real failure reasons + real cost figure
- [x] **Verify:** confirm cost numbers come from logged data, not estimates

## Phase 4 — Dashboard
- [x] Violations view: sites/scans, prioritized violations, before/after diffs, verification status
- [x] System Performance tab: throughput, pipeline time (median/p95), per-agent latency+success%, cache hit%, verification breakdown, scan success rate, PR metrics, accessibility score trend
- [x] Review & Approve tab: side-by-side diff viewer + approve/reject + "Generate fixed page" →
      "Download fixed page" (real PyGithub PR deferred to optional Phase 6 — see design.md
      Section 11; human click still required for every step, no fully-automatic path)
- [x] **Deliverable:** clickable fullstack demo — detection, reasoning, cost, approval end to end
- [x] **Verify:** 81 backend tests passing (up from 52 at Phase 3 close), `ruff check` clean,
      frontend `tsc -b && vite build` clean, full containerized stack (`docker compose up`)
      built and live-verified via real Playwright browser automation against real dev-DB
      data — golden path (approve → generate → download) and the violations_remain edge
      case (no download button) both confirmed, zero browser console errors, two real
      layout bugs found and fixed (bar-chart label collision, diff-viewer horizontal
      overflow) rather than shipped unnoticed

## Phase 4.5 — Frontend testing + CI/CD (backlog, placeholder scope only)
**Note:** placeholder, same pattern as design.md Section 10 was handled
before Phase 2.5 started — no tooling decisions invented here. Fill in
for real once frontend work in Phase 4 actually starts.
- [x] Full frontend test suite (component tests — likely Vitest/React
      Testing Library or whatever fits the eventual frontend stack,
      decided when this phase starts, not now)
      *(Vitest + React Testing Library, no MSW — see design.md Section 12.
      60 tests across components, the useScanSelector hook, api/client.ts,
      and all three pages.)*
- [x] Extend `.github/workflows/ci.yml` (or add a parallel job) to
      lint/test/build the frontend on every push — same enforcement
      standard Phase 2.5d built for the backend (real triggered Actions
      runs, proven to fail on a real regression and recover, not just
      YAML review)
      *(New independent `frontend` job, no Postgres/backend services.)*
- [x] **Deliverable:** CI gate covers frontend + backend together, not
      backend only
- [x] **Verify:** same red/green proof standard as Phase 2.5e — CI green
      on a clean run, red when an intentional regression is reintroduced
      *(Red run 29124818143 — inverted ReviewApproveView.tsx's download-
      link gate, exactly the 3 download-gating tests failed, nothing
      else. Green run 29124965399 after a byte-clean revert.)*

## Phase 4.6 — Crawler bot-blocking / status-code handling
      **Note:** found while asking "what happens against a site that blocks bots"
      before scoping Phase 5 — Phase 5 crawls 30-50 real public sites, so a
      silent-bad-data gap here would quietly corrupt that eval sample rather than
      show up as a visible failure. Fix before Phase 5, not during it.
      - [x] Improve `backend/app/crawler.py`'s per-page load handling:
            - [x] Check `response.status` after `page.goto()` (Playwright does not
                  raise on 4xx/5xx by default — only on network-level errors or
                  timeout) and treat 403/429/503 as `status="failed"` with a
                  `failure_reason`, same as an existing timeout/network failure
                  *(`BLOCKED_STATUS_CODES = {403, 429, 503}`; scoped to exactly
                  these three per user decision — 404/500/etc. stay "loaded",
                  those are real app errors, not bot-blocking.)*
            - [x] Basic bot-challenge/CAPTCHA sniff on pages that return 200 but
                  aren't the real page (e.g. Cloudflare/challenge markers in the
                  DOM or title) — classify as failed rather than scanning the
                  challenge page for violations
                  *(`CHALLENGE_MARKERS` substring sniff against rendered HTML —
                  heuristic, not exhaustive, documented as such.)*
            - [ ] Consider a non-default-headless-looking User-Agent if fingerprint-
                  based blocking shows up in testing (decide from real evidence,
                  not speculatively)
                  *(Deferred — no fingerprint-based blocking evidence found during
                  verification; default headless Chromium UA loaded httpbin.org
                  and example.com normally. Revisit if real evidence surfaces.)*
      - [x] **Deliverable:** crawler distinguishes "page didn't load" from "page
            loaded but we were blocked," and never silently scans a block/CAPTCHA
            page as if it were real site content
      - [x] **Verify:** run against at least one real site known to block bots
            (e.g. one that returns 403 or a Cloudflare challenge to headless
            Playwright) and confirm it's logged as `failed` with an accurate
            `failure_reason`, not scanned
            *(httpstat.us was unreachable/down at verification time — real curl
            showed the server closing the connection abruptly. Used httpbin.org's
            `/status/403`, `/status/429`, `/status/503` instead: `python
            crawler.py https://httpbin.org/status/403` (and 429, 503) each
            reported `[failed] ... — blocked (status N)`, 0/1 loaded, 0
            violations — confirming the blocked page is never scanned. Regression
            check: `https://httpbin.org/status/200` and `https://example.com`
            both still reported `[loaded]` normally. Full suite: 88/88 backend
            tests passing, including 5 new crawler tests for 403/429/503/
            challenge-page/no-link-extraction.)*

## Phase 5 — Evaluation & Metrics
- [x] **Step 0 — Eval scaffolding + guardrails** (this is infrastructure,
      not a real run — no site in `eval/eval_corpus_30_sites.csv` has
      actually been scanned yet):
      - [x] `backend/app/eval_runner.py` — resumable Pass 1 orchestrator
            (crawl+detect, free, then Reviewer-only confidence scoring,
            budget-gated). Checkpoints every site/violation to
            `eval/progress_pass1.json` so a stop mid-run resumes without
            re-crawling or re-spending Groq budget. Hard-refuses to start
            if `LLM_MOCK=true`.
      - [x] Daily-RPD budget guard: `EVAL_DAILY_CALL_CAP`/
            `EVAL_DAILY_CAP_SAFETY_MARGIN_PCT` (config.py, default
            1000/0.9 — confirm your org's real limit at
            console.groq.com/settings/limits before a real run), checked
            against real `llm_call_logs` rows (`is_mock=false,
            cache_hit=false`, today, matching model) before every Reviewer
            call, filtered by model not agent_name since Groq's RPD cap is
            per-model-per-account.
      - [x] `backend/app/eval_sampling.py` — stratified sampler
            (`wcag_rule` x confidence bucket) feeding `sample_pass2.csv`
            directly; `sample_manual_labeling.csv` is the distinct pages
            that same sample touches, so a human has full-page context for
            recall, not just a per-violation judgment call.
      - [x] `backend/app/eval_report.py` — real function signatures for all
            four metrics, structure only, no calculation logic yet (needs
            real Pass 1/Pass 2 data + hand-filled labels first).
      - [x] `eval/manual_labels.csv`, `eval/fix_spotcheck.csv` — header-only
            templates. `eval/progress_pass2.json` — empty schema shell.
            `eval/progress_pass1.json` — real file, generated for real
            (free, deterministic, zero Groq calls) from the actual 30-site
            corpus, all `pending`.
      - [x] `EVALUATION.md` — section headers only, all TBD.
      - [x] `backend/tests/eval/` — 17 new tests (budget threshold/DB
            counting, manifest init/resume/skip/budget-stop, stratified
            sampling), no real Groq calls or live crawling — `crawler.
            crawl_site`/`reviewer_node` monkeypatched. Full suite:
            105/105 passing.
- [ ] Run pipeline across 30-50 real public sites
- [ ] Manually label 15-20 pages → real precision/recall/false-positive rate
- [ ] Spot-check sample of "verified" fixes → false verification rate
- [ ] Confidence calibration: high vs low Reviewer confidence_score vs actual outcome
- [ ] **Guardrail (decided Phase 2, see design.md Section 9):** eval runner
      must hard-refuse to start if `LLM_MOCK=true`. Keep the persistent
      cache enabled (don't disable it for eval) but filter calibration
      calculations to `cache_hit=false` rows only, to avoid pseudo-
      replication biasing the numbers.
- [ ] **Guardrail (decided Phase 2):** track/report `llm_call_logs.error`/
      `error_type` failure rate per rule type — a rule with a
      disproportionately high reasoning-failure rate would otherwise be
      silently under-represented in the eval sample.
- [ ] Track cumulative `llm_call_logs` usage against Groq's real measured
      daily cap (see design.md Section 7 — 6,000 tokens/minute measured
      live, tighter than the RPM figure originally planned around)
- [ ] **Deliverable:** EVALUATION.md — defensible numbers, no invented figures

## Phase 6 — Open Source Contribution (capstone)
- [ ] Pick target repo (Carbon / Lightning Design System / React Spectrum / Fluent UI)
- [ ] Run full pipeline including human-approval step
- [ ] On approval: PyGithub fork → branch → commit → push → PR
- [ ] **Budget extra buffer time** — this chain is fiddlier than it looks
- [ ] **Deliverable:** real, linkable PR

## Phase 7 — Polish & Packaging
- [ ] Update design.md to reflect what was actually built + tradeoffs hit
- [ ] README: setup, screenshots/GIF of dashboard (incl. System Performance + Approve tabs), real eval numbers
- [ ] Resume bullets written only from numbers you can show logs for

---
### Session log (append as you go)
<!-- 2026-07-02: Started Phase 0 -->
<!-- 2026-07-04: Phase 1 — standalone Playwright load + axe-core detection proofs verified across 7 real sites; added axe-core rule filtering (runOnly) restricted to the locked 9; built real crawler.py (same-domain BFS, max_pages=15, max_depth=2, critical-path URL prioritization, skip+log on failure); documented crawler + rule-filtering design choices in design.md Sections 4b/4c. detector.py still a standalone proof, not yet a real module. -->
<!-- 2026-07-05: Phase 1 complete — detector.py promoted from standalone proof to real module (LOCKED_RULE_IDS via runOnly, structured Violation dataclasses, one row per rule+element); built FastAPI+Postgres API layer (config.py, db.py, models.py, main.py), Alembic migration for all 8 schema.md tables (+pages.status/failure_reason, +violations.html_snippet/message per decisions logged in docs/schema.md), docker-compose Postgres on host port 5433 (5432 conflicts with a pre-existing native Postgres service on this machine). Verified end-to-end against 3 real URLs: usa.gov (15 pages, 1 violation), news.ycombinator.com (15 pages, 530 violations), example.com (1 page, 0 violations). Confirmed BackgroundTasks non-durability limitation live via kill-mid-scan test. Fixed a datetime timezone bug and an Alembic enum-cleanup gap found during verification. Documented in design.md Section 3 that "keyboard traps" (2.1.1) are not statically detectable and are NOT covered by the `tabindex` rule — v1 only catches the positive-tabindex anti-pattern; flagged so Phase 5 eval doesn't overstate 2.1.1 coverage. -->
<!-- 2026-07-05: Starting Phase 2 planning next. -->
<!-- 2026-07-06: Phase 2 complete — LangGraph 4-node reasoning layer built
     (backend/app/graph.py + agents/{reviewer,impact,developer,verifier}/ +
     llm_client.py). LLM stack changed from CLAUDE.md's original local-Ollama
     plan to qwen/qwen3-32b via Groq's free API — this machine had only
     ~2.2GB RAM free of 16GB, real swap-thrashing risk for a local 7B model;
     full reasoning + a real Groq benchmark (qwen3-32b vs gpt-oss-120b) in
     design.md Section 7. Discovered live (not predicted) that Groq's real
     binding constraint is 6,000 tokens/minute, not the RPM figure planning
     assumed — confirmed via x-ratelimit-limit-tokens header and a real 43-
     violation scan (W3C's WAI "bad" demo page) that hit real 429s after the
     first few calls. Added is_mock/error/error_type columns to
     llm_call_logs + a Reviewer-only persistent llm_response_cache table
     (Alembic migration 347a304e5105). Verified live end-to-end: (1) a real
     violation went through all 4 nodes and landed correctly in Postgres
     (confidence=0.98, real impact reasoning, a real proposed color-contrast
     fix anchored to the exact element_selector); (2) a real 429 mid-graph
     (on Developer, after Reviewer+Impact succeeded) left zero rows in
     impact_assessments/fixes and null confidence — confirmed via direct
     psql query, proving the "no partial state" design holds under a real
     failure, not just a staged one; (3) cache_hit=true with 0ms/0 tokens on
     a repeated identical violation; (4) LLM_MOCK=true via the real /scan
     endpoint produced 43/43 mock-reasoned violations and 129/129 is_mock=true
     log rows with zero real Groq calls. Subagent review confirmed exactly 4
     nodes, no scope creep, no unnecessary abstraction. Phase 5 guardrails
     (mock hard-refuse, cache_hit exclusion from calibration, per-rule
     failure-rate tracking) documented now in both PLAN.md's Phase 5 section
     and design.md Section 9, to be enforced when Phase 5 starts. -->
<!-- 2026-07-06: Phase 2 addendum (not part of the originally approved
     Phase 2 plan) — added rate-limit-aware pacing to llm_client.py after
     Phase 2's own verification surfaced real, repeated 429s on anything
     past a handful of violations. Added now rather than deferred to
     Phase 3 because it's a different problem than Phase 3's planned cost
     optimization: caching/model-routing = fewer calls; this = don't
     exceed the rate of calls made. Implementation: module-level
     remaining-tokens/reset-deadline state read from Groq's real response
     headers after every real call, an asyncio.Lock so concurrent scans
     can't race past the shared per-account budget, adaptive sleep only
     when remaining tokens drop below a 1,000-token safety margin
     (observed real calls run ~400-700 tokens). Verified live: back-to-back
     calls ran with zero delay while budget was healthy; a call correctly
     detected 35 remaining tokens and slept 59.61s (the real reset window
     Groq reported) rather than hitting a 429. Full reasoning in design.md
     Section 8b. Existing per-violation failure handling (error_type=
     rate_limited, clean skip) is unchanged — this is a proactive layer in
     front of it, not a replacement.
     Full-scale verification (re-ran the same 43-violation W3C page that
     was 43/43 failed unpaced): 124 real calls, 118 succeeded, 6 failed —
     exactly matching the 6/43 violations left without confidence
     (100%→14% violation failure rate). First comparison attempt used a
     wrong time window (bare timestamp read as UTC by Postgres pulled in
     unrelated earlier testing, inflating the failure count to a
     misleading 88) — caught and corrected using the scan's real
     started_at/completed_at before reporting. Raised TOKEN_SAFETY_MARGIN
     1000→1500 after seeing Developer calls run up to 1362 tokens, above
     the original margin — full numbers and reasoning in design.md
     Section 8b. -->
<!-- 2026-07-06: Also fixed a subtly-wrong claim in design.md Section 8b
     found during Phase 1+2 coordination testing (scan 14, usa.gov):
     Groq's non-strict json_object mode does not "guarantee valid JSON
     syntax" as documented — it can hard-reject a generation with a 400
     json_validate_failed and zero recoverable content (failed_generation
     empty), reproduced directly, not transient. Already safely handled
     as a generic http_error; only 2 data points, so no code change — real
     per-rule failure-rate data during Phase 5 is the actual trigger to
     investigate further. -->
<!-- 2026-07-06: Re-verified TOKEN_SAFETY_MARGIN=1500 at the same full
     43-violation scale as the 1000 baseline (previously only import-
     checked, not scan-tested) — 129/129 real calls succeeded, 0 failures
     of any kind, 43/43 violations got full confidence/impact/fix. Closes
     the loop: the residual failures at margin=1000 (118/124 calls, 37/43
     violations) really were a margin-sizing problem. This was the last
     open item before considering Phase 2 (incl. both addenda) fully
     verified end to end. -->
<!-- 2026-07-07: Inserted Phase 2.5 (Automated Test Suite + CI/CD Pipeline)
     between Phase 2 and Phase 3, documentation-only. Rationale: no
     automated test suite or CI exists yet — Phase 1 and Phase 2 were both
     verified via live manual runs + direct psql checks, not pytest.
     CLAUDE.md already stated CI intent ("GitHub Actions — lint + test on
     every push") but it was never built. Phase 3 (applies fixes to live
     DOM, re-verifies) is the highest-risk, most regression-prone code so
     far, so real regression coverage needs to exist before Phase 3 starts,
     not be retrofitted after. No code, tests, or CI config written yet —
     Plan Mode for 2.5a starts next per CLAUDE.md's workflow rule. -->
<!-- 2026-07-07: Phase 2.5a complete — test infrastructure built and
     verified live, not just by a single green pytest run. Added
     `postgres_test` as a profile-gated service in docker-compose.yml
     (`profiles: ["test"]`, port 5434, DB `accessibility_agent_test`) rather
     than a docker-compose.override.yml, since that file is already
     gitignored and wouldn't be shared via git. Added a one-line
     conditional guard to migrations/env.py so a caller-set
     `sqlalchemy.url` isn't clobbered back to the dev DB, letting a
     session-scoped autouse pytest fixture (backend/tests/conftest.py) run
     the real Alembic chain against the test DB instead of a hand-built
     schema. `.env.test` forces LLM_MOCK=true (confirmed gitignored via
     `git check-ignore -v`, no new .gitignore pattern needed for it).
     `requirements.txt` gained pytest==9.1.1 + pytest-asyncio==1.4.0,
     regenerated via `pip freeze` while preserving its existing UTF-16LE
     encoding (confirmed via `file`) — diffed to confirm only the new
     packages + transitive deps changed.
     Verified beyond the first green run: (1) direct `psql` into the test
     container independently confirmed all 10 tables + `alembic_version`
     at the real head (347a304e5105), while the dev DB's real data (4
     sites, 15 scans) was unchanged after the test run; (2) plain `docker
     compose up -d` (no --profile) does NOT start postgres_test — confirmed
     by stopping it and checking `docker compose ps` only listed the dev
     service; (3) `alembic current`/`upgrade head` against the dev DB via
     the normal CLI still resolves correctly post-env.py-change, confirming
     the guard didn't break the existing dev migration workflow; (4) pytest
     re-run 3 times total (across a mid-run container restart and a
     stop/start cycle) stayed green each time, not a lucky first pass.
     One first-run failure caught and explained, not hidden: the very
     first `pytest` invocation hit a real asyncpg connection error because
     the container was still `health: starting`, not yet `healthy` — a
     race, not a code defect; passed cleanly once healthy.
     Explicitly not yet provable: `.env.test`'s LLM_MOCK=true is confirmed
     present in the test environment, but no code in 2.5a's test suite
     calls llm_client.py, so it hasn't yet been proven to actually prevent
     a real Groq call — that's 2.5c's job once graph/mock regression tests
     exist. 2.5b/c/d/e untouched — no regression tests, no CI YAML, no lint
     tooling added this session. -->
<!-- 2026-07-07: Phase 2.5b complete — 28 real pytest tests added (26 new +
     2.5a's original 2), all green: `pytest backend/tests/ -v` →
     "28 passed" (confirmed stable across 2 consecutive full runs). No real
     internet, no real Groq, no real dev DB touched — confirmed directly
     (dev `sites`/`scans` row counts unchanged at 4/15 before and after).
     Detector: 17 tests (backend/tests/detector/test_detector.py) against
     16 static HTML fixtures under backend/tests/fixtures/detector_pages/,
     each hand-run against the real axe-core detector before being trusted
     as a fixture. 13 fixtures each assert exactly one expected
     (rule, severity) pair with zero noise from the other 8 locked rules;
     one clean-page control asserts zero violations; one multi-violation
     fixture proves one Violation row per (rule, element).
     Real gap discovered during fixture verification (not previously
     documented — see design.md Section 3 addendum): `bypass` and
     `duplicate-id-aria` are marked `reviewOnFail: true` in axe-core's own
     rule metadata, so a genuine failure of either lands in axe's
     `incomplete` result array, not `violations` — detector.py's
     detect_violations() only reads `violations`, so these 2 of 9 locked
     rules can never produce a Violation row under the current
     implementation, confirmed via raw axe runs against fixtures that
     genuinely fail the rule. Codified as known-gap tests rather than
     fixed (out of scope for a regression-test session; user confirmed this
     approach). `skip-link` (the other Bypass Blocks rule) resisted several
     genuine hand-construction attempts this session and was left
     undetermined rather than asserted on unverified behavior — no fixture
     added for it.
     Crawler: 8 tests (backend/tests/crawler/test_crawler.py) against a
     7-page local fixture site (backend/tests/fixtures/crawler_site/) served
     by a new stdlib `ThreadingHTTPServer` (backend/tests/fixtures/server.py,
     no new dependency) — same-domain restriction (external link never
     resolved, string-compared only), max_depth capping (1 vs 2 vs 3 hops),
     max_pages capping, priority-pattern queue ordering, and skip+log via
     two real failure modes: navigation timeout (a monkeypatched-down
     PAGE_LOAD_TIMEOUT_MS against a /slow endpoint) and connection-refused
     (an unbound local port) — confirmed during planning that a plain HTTP
     404 does NOT trigger crawler.py's failure path today (page.goto()
     doesn't raise on non-2xx), so 404 was deliberately not used as a
     skip+log trigger.
     API: 1 test (backend/tests/api/test_scan_roundtrip.py) — real POST
     /scan → GET /scan/{id} round-trip via httpx's ASGITransport
     (in-process, no real socket) against main.app, pointed at the test DB
     by setting DATABASE_URL before main.py's first import (pydantic-
     settings env-var-over-env-file precedence; no app code touched).
     Confirmed via starlette source that BackgroundTasks run inside the
     same ASGI response cycle, so the POST already returns a terminal scan;
     a bounded-retry poll is still used defensively. Asserts the persisted
     violation directly against the test DB (not just the API response),
     and asserts the scan's URL is absent from the real dev DB.
     Infra fix: `test_engine` (backend/tests/conftest.py) switched from a
     pooled to a NullPool engine — the pooled version's `pool_pre_ping`
     failed with a raw `AttributeError` (not a clean DBAPI error it knows
     how to recover from) when a connection opened early in a session went
     stale after the many Playwright browser launches 2.5b's detector/
     crawler tests perform; reproduced directly running the full suite
     before the fix, resolved after, confirmed stable across 2 full runs.
     Real bug not guessed: launching Playwright inside a `@pytest.fixture`
     (async generator, any scope, `async with` or explicit start/stop)
     hung silently every time (zero output, zero CPU on the spawned
     chrome-headless-shell processes) — a standalone script outside pytest
     doing the identical sequence completed in under a second, isolating
     pytest-asyncio's fixture machinery as the trigger. Fixed by not using
     a fixture for it at all — a plain helper function called directly from
     each test body, which never hung. Documented in test_detector.py's
     module docstring so this isn't rediscovered later.
     Regression-catch proof: temporarily reverted models.py's
     `_TZ_DATETIME` to `DateTime(timezone=False)` and applied a real
     throwaway Alembic migration (test DB only) changing
     scans.started_at/completed_at back to `timestamp without time zone` —
     reproducing the exact original mismatch (a code-only attempt first,
     reverting main.py's datetime.now(timezone.utc) calls to naive, did
     NOT reproduce it: asyncpg encodes by the DB's actual column type, not
     the ORM annotation, so that direction is silently fine). With both
     reverted together, test_scan_roundtrip.py failed with the identical
     error PHASE1_COMPLETION_REPORT.md recorded:
     `asyncpg.exceptions.DataError: ... can't subtract offset-naive and
     offset-aware datetimes`. Reverted models.py, downgraded the test DB
     via `alembic downgrade` (the project's own tooling, using the same
     explicit-URL pattern conftest.py uses — the bare CLI defaults to the
     dev DB via app/config.py and was confirmed to have safely no-opped
     against it since dev was already at head), deleted the throwaway
     migration file, then reran the full suite green (28 passed) as final
     confirmation. Dev DB confirmed untouched throughout (4 sites/15 scans,
     unchanged before/after the whole session).
     2.5c/d/e untouched — no Phase 2 reasoning tests, no CI YAML, no lint
     tooling added this session. -->
<!-- 2026-07-07: Added Phase 2.6 (backlog, not started) between Phase 2.5
     and Phase 3, documentation-only — no code, test, or design.md changes
     this entry. Captures the `bypass`/`duplicate-id-aria` `reviewOnFail`
     gap found during Phase 2.5b fixture verification (see Phase 2.5b's
     session-log entry and design.md Section 3) as real follow-up work
     rather than letting it sit undiscoverable in a completed phase's
     history: only 2 of the 9 locked rules were checked for this gap, by
     accident, not via a full audit, so Phase 2.6 starts with auditing all
     9 before deciding a fix. Added a one-line pointer note at the top of
     Phase 3 so verification-logic work there doesn't implicitly assume
     all 9 locked rules are reachable via detect_violations() before this
     is resolved. -->
<!-- 2026-07-08: Phase 2.5c complete — 13 real pytest tests added
     (backend/tests/graph/), all green alongside 2.5a/b's original 28:
     `pytest backend/tests/ -v` → "41 passed", confirmed stable across 3
     consecutive full runs (plus 2 isolated `backend/tests/graph/`-only
     runs before that). No real Groq call, no real dev DB touched —
     confirmed directly (dev `sites`/`scans` unchanged at 4/15 before and
     after every run this session).
     graph/test_graph_sequence.py (3 tests): calls `reasoning_graph.
     ainvoke()` directly on a non-critical-path violation, asserting all 4
     node result types plus — queried straight from llm_call_logs, not
     inferred from the return value — exactly one real is_mock=true row
     each for Reviewer/Impact/Developer and zero for Verifier; a second
     test proves the Impact critical-path URL heuristic genuinely bypasses
     the LLM (zero new Impact log rows, not just "the mock response looked
     right"); a third pins the Verifier stub's `pending_verification`
     status and its zero-log-rows contract, deliberately not exercising
     any Phase 3 DOM-recheck behavior.
     graph/test_partial_state.py (1 test): the "no partial state" guarantee
     is actually enforced by main.py's run_scan (single ainvoke() +
     single-commit per violation), not by graph.py itself — graph nodes
     never touch the DB — so this test runs the real API layer (POST /scan
     against the existing `api_scan_target.html` fixture) rather than
     calling ainvoke() in isolation. Forces a deterministic Developer-only
     failure by monkeypatching `llm_client._call_mock` (call_llm() resolves
     it as a same-module global at call time, so the patch takes effect
     with zero edits to llm_client.py/graph.py). Confirms: scan still
     reaches status="done" (a per-violation reasoning failure doesn't fail
     the whole scan), zero rows in impact_assessments/fixes for that
     violation, violations.confidence stays NULL, and exactly 2 real
     llm_call_logs rows (Reviewer, Impact) were written before the forced
     failure — proving the graph got 2 nodes deep, not that it failed
     immediately.
     graph/test_llm_client_cache.py (3 tests) + test_llm_client_error_logging.py
     (6 tests): both call `_call_real` directly with only the network seam
     (`_make_paced_request`) monkeypatched, since the Reviewer cache and
     error_type classification are only reachable through `_call_real`
     (LLM_MOCK short-circuits before both). Cache tests prove a repeated
     identical input is a real DB-backed cache_hit (second call's
     `_make_paced_request` raises if invoked — cache hit never touches
     it), that whitespace/tag-case variants collide to the same cache_key,
     and that a differing attribute *value* does not (2 distinct cache_key
     rows, network hit twice) — the conservative-normalization claim
     proven both directions, not just asserted. Error-logging tests drive
     all 6 real `_classify_error` branches (timeout, rate_limited,
     http_error, json_decode_error, validation_error, unknown) through
     genuine code paths (a raised httpx exception, or a crafted
     httpx.Response per case), each asserting the exact `is_mock`/
     `error_type` column values via direct DB query, not just row count.
     Regression-catch proof (not just asserted): temporarily replaced
     run_scan's single `ainvoke()`+commit with an incremental
     per-node-call/per-commit version (a realistic historical version of
     this bug class — commit ImpactAssessment right after impact_node
     succeeds, before developer_node is even attempted). Re-ran
     test_partial_state.py: failed exactly as expected, with a real
     confidence=0.9 committed despite the forced Developer failure
     (`assert violation["confidence"] is None` → `AssertionError: assert
     0.9 is None`). Reverted main.py to its original form; `git diff
     --stat`/`git diff` on backend/app/main.py confirmed empty before
     re-running the full suite green again (41 passed) — the transient
     edit never landed in the working tree.
     Infra fix (not anticipated in planning): db.py's module-level pooled
     engine (`pool_pre_ping=True`) is a singleton shared across every test
     subpackage that imports main/db (api/, and now graph/), reused across
     many test-function event loops. Hit the identical stale-asyncpg-
     connection `AttributeError` 2.5b fixed for `test_engine` via NullPool
     — but db.py is production code, not something to repoint. Fixed via a
     test-only autouse fixture in graph/conftest.py that disposes
     `db.engine`'s pool both before and after every test in that directory
     (before, in case api/'s tests already poisoned it earlier in the same
     session; after, so the next test in any directory starts clean).
     Also fixed a now-stale comment in api/conftest.py ("no other test
     file imports main/db/config") that graph/conftest.py's addition
     invalidated — comment-only edit, verified via an isolated
     `pytest backend/tests/api/ -v` run (still 1 passed) that it didn't
     touch fixture behavior.
     2.5d/e untouched — no CI YAML, no lint tooling, no re-verification of
     2.5a/b beyond the full-suite re-runs above. -->
<!-- 2026-07-08: Phase 2.5d complete — real `.github/workflows/ci.yml`,
     verified via actual triggered GitHub Actions runs on PR #11
     (SiddhiKhairee/accessibility-compliance-agent), not just YAML review.
     Confirmed 2.5a/b/c green locally first (41 passed) before starting,
     per this session's own gate.
     Added `ruff` (zero custom config — no ruff.toml/pyproject.toml; its
     built-in default rule set was sufficient). `ruff check backend/`
     surfaced exactly one real finding across the entire pre-2.5d
     codebase: an unused `import pytest` in `backend/tests/crawler/
     test_crawler.py` (a 2.5b file) — fixed as a user-approved, explicit
     exception to "don't touch 2.5a/b/c test files" (one-line, zero-
     behavior-risk removal). Re-ran the full suite after: still 41 passed.
     First real CI run (not the deliberate one) failed unexpectedly:
     `test_scan_roundtrip.py`'s isolation check reads `backend/app/.env`
     (gitignored, absent in a fresh checkout) via `dotenv_values()` to
     prove a scan never touched the dev DB — `assert dev_database_url is
     not None` failed since the file didn't exist. Root-caused and fixed
     without touching that test file: switched from job-level env vars to
     writing real `.env`/`.env.test` files, backed by *two* Postgres
     services mirroring docker-compose.yml exactly (5433 dev / 5434 test,
     not just one), with Alembic applied to both — the dev DB needed its
     real schema present (a `sites` table), not just to exist, since the
     isolation check queries it directly. Full reasoning in design.md
     Section 10.
     Verified live via `gh` CLI (installed and authenticated mid-session
     for this purpose) against real triggered runs, not local YAML
     inspection: fixed config green on both trigger paths — run
     `28919086956` (push) and `28919088480` (pull_request), both
     `conclusion: "success"`, both reporting the identical `41 passed` the
     local suite shows. Then proved the gate actually fails: pushed a
     deliberate, throwaway unused-import violation — run `28919211909`
     came back `conclusion: "failure"`, red specifically at the Lint step
     (Playwright install/Alembic/pytest steps correctly never ran,
     confirming the fail-fast step ordering). Reverted (diff against the
     pre-violation commit confirmed empty) and pushed again — run
     `28919267276` came back `conclusion: "success"`, `41 passed` again.
     ubuntu-latest chosen over windows-latest: nothing in the app is
     Windows-specific, and the Windows-ProactorEventLoop stale-pooled-
     connection quirk 2.5b/2.5c worked around never became CI-relevant on
     Linux's default SelectorEventLoop (the dispose-fixture still runs,
     it just never hits the failure mode it guards against). Python 3.14
     to match the local dev venv exactly.
     2.5e untouched — no re-verification of the datetime-tz regression
     specifically, no CLAUDE.md/PLAN.md/design.md full rewrite (this
     entry + design.md Section 10's CI subsection are additive, not that
     rewrite). PR #11 held open, not yet merged, pending final review. -->
<!-- 2026-07-08: PR #11 merged to main as 7598387 (squash), branch
     deleted. Post-merge CI on main: run 28919812633, success. -->
<!-- 2026-07-08: Phase 2.5 fully closed (2.5e — verify & close). Fresh
     full local suite at session start: 41 passed (matches 2.5d, no
     drift). Full narrative in PHASE2_5_COMPLETION_REPORT.md; summary
     here.
     Consolidated CI-level regression proof (distinct from every prior
     2.5b/c/d proof, which were either local or lint-only): reintroduced
     the real Phase 1 datetime-tz bug (models.py's _TZ_DATETIME reverted
     to DateTime(timezone=False), plus a throwaway migration altering
     scans.started_at/completed_at back to TIMESTAMP WITHOUT TIME ZONE)
     on a real PR (#12). Quick local sanity check first (reproduced the
     exact original DataError, fully reverted before touching git).
     Real CI red: run 28920503993, conclusion=failure — 12 failed, 29
     passed, broader than planning assumed: _TZ_DATETIME is one shared
     constant used by every timestamp column (sites.last_scanned_at,
     scans.*, fixes.verified_at, approvals.decided_at,
     llm_call_logs.created_at, llm_response_cache.created_at), so
     reverting it broke every write path touching any of them, not just
     the one migration this session altered — confirmed via the real
     generated SQL in the CI log (llm_call_logs inserts also cast
     created_at as ::TIMESTAMP WITHOUT TIME ZONE). All 12 failures were
     the identical real asyncpg DataError, reported as the real wider
     number rather than the originally-assumed narrower one. Reverted;
     git diff/--stat against the pre-regression commit confirmed empty
     before pushing. Real CI green: run 28920679468, conclusion=success,
     41 passed. PR #12 closed without merging (branch was byte-identical
     to main after revert), branch deleted.
     Branch protection added on main (your explicit go-ahead, a real
     repo-settings decision, not code): required_status_checks.checks=
     [{"context":"test"}], strict=true, enforce_admins=true,
     allow_force_pushes=false, allow_deletions=false. Confirmed 404
     "Branch not protected" beforehand, confirmed active via the API
     afterward.
     Documentation closure this session: PHASE2_5_COMPLETION_REPORT.md
     (new, matches PHASE1/PHASE2's format), design.md Section 10 expanded
     from a PLAN.md-pointer to inlined 2.5a-e decisions, design.md
     Section 3 gained an explicit "(tracked as Phase 2.6)" pointer next
     to the bypass/duplicate-id-aria writeup, CLAUDE.md's CI line updated
     from aspirational to real-and-enforced (PR #11 referenced).
     Phase 2.5 (2.5a-e) is now fully closed. Phase 3 — real fix-
     application + reverification, "the highest-risk, most regression-
     prone code so far" — is gated by a CI pipeline proven, not assumed,
     to both pass on real green and fail on a real regression. -->
<!-- 2026-07-08: Phase 2.6 complete — the reviewOnFail gap 2.5b found by
     accident is now closed, not just documented. Audit (live, not
     inferred): loaded the real bundled axe.min.js in headless Chromium
     and queried axe._audit.rules directly for reviewOnFail across all 16
     rule IDs spanning the 9 locked rules — confirmed only bypass and
     duplicate-id-aria are reviewOnFail:true; nothing else was silently
     missed, including skip-link (previously left "undetermined" in 2.5b
     for an unrelated reason, now confirmed reviewOnFail:false).
     Decision (written to design.md Section 3 before implementing, per
     CLAUDE.md workflow): read axe's `incomplete` array, scoped narrowly to
     just these 2 rule IDs (REVIEW_ON_FAIL_RULE_IDS in detector.py), and
     tag the resulting Violation rows detection_confidence="needs_review"
     vs "confirmed" for normal violations — doesn't violate Phase 0's
     "no manual-judgment rules" lock since detection stays fully automated
     and the existing Reviewer Agent is the natural place to eventually use
     the signal, not a new 5th LangGraph node.
     Real pre-flight check before writing the extraction loop (user-
     requested, not assumed): ran a raw axe call against the exact
     no_bypass.html/duplicate_id_aria.html fixtures 2.5b proved genuinely
     fail their rule, and printed the real incomplete node objects —
     confirmed `impact` (which becomes `severity`) is present and non-null
     for both (serious/critical respectively), so the existing
     `v["impact"] or "unknown"` fallback could be reused as-is with no
     special-casing.
     Implementation: detector.py's detect_violations() gained a second
     extraction loop over results.response["incomplete"], filtered to
     REVIEW_ON_FAIL_RULE_IDS; AXE_OPTIONS resultTypes extended to include
     "incomplete". New nullable violations.detection_confidence column
     (String(20), matching the existing severity-is-plain-String
     precedent, not a Postgres enum) via Alembic revision 92f78d8d9d6b,
     wired through main.py's run_scan and ViolationOut. docs/schema.md and
     design.md both carry an explicit note: pre-migration rows are NULL,
     not "confirmed" — no backfill planned, flagged so a future
     WHERE detection_confidence='confirmed' query doesn't silently drop
     them. design.md also carries an explicit known-limitation note: this
     phase only makes needs_review violations surface/persist, it does not
     change how the Reviewer/Impact/Developer/Verifier nodes treat them —
     deferred, not decided, to avoid quietly creating a second undocumented
     gap in place of the first.
     Verified: full suite 42 passed (41 prior + 1 net new — the 2
     known-gap tests flipped from "asserts absence" to "asserts presence
     with detection_confidence=='needs_review'", plus 1 new regression
     test confirming the other 13 rule IDs never produce a needs_review
     row). Migration applied and confirmed via direct psql on both the dev
     DB (995 existing violations rows, all NULL on the new column, count
     unchanged before/after) and the test DB (column present via \d
     violations). -->
<!-- 2026-07-09: Phase 3 complete — Verifier is real, no graph
     restructuring (still exactly 4 nodes). New flat module
     backend/app/verifier.py (`verify_fix()`, same own-Playwright-lifecycle
     convention as detector.py/crawler.py, no DB access): pre-apply
     html.parser tag-balance sanity check, real page load, outerHTML
     replacement at target_selector via Locator.evaluate(), full
     detect_violations() rerun, diff against the page's pre-fix baseline
     (threaded into ReasoningState by run_scan — nodes still never touch
     the DB). graph.py's verifier_node wraps this with one mechanical
     retry (same proposed_code_diff, fresh page load, no new Developer LLM
     call) before landing on verified/rejected/manual_review.
     Design decisions confirmed with user before implementation: rejected
     = clean technical run but violation persists/new one appeared,
     failure_reason=None; manual_review = a technical failure that
     persisted through the retry, failure_reason set; on a mixed
     first-attempt-vs-retry outcome, the retry's own result always wins;
     verified_at stamps on any terminal verdict, not only verified
     (matches scans.completed_at's stamp-on-success-or-failure precedent).
     Cost optimization: Developer is now cached (generalized the existing
     Reviewer-only cache key to include agent_name; a cache hit always
     overrides target_selector with the current call's element_selector,
     never the cached value, since target_selector is a verbatim copy of
     input, not independently generated content — see
     test_developer_cache_hit_overrides_target_selector). Impact's
     LLM-fallback now routes to IMPACT_FALLBACK_MODEL_NAME
     ("llama-3.1-8b-instant") instead of qwen/qwen3-32b; Reviewer/Developer
     untouched.
     Two real bugs found and fixed via live verification against the real
     Groq API (not just mocked tests), matching CLAUDE.md's own bar for
     verifying model/rate-limit claims live: (1) `reasoning_format:
     "hidden"` is qwen3-specific — Groq returns a hard 400 for
     llama-3.1-8b-instant, reproduced directly via a real scan's Impact
     call failing this way; payload now only sends it when
     resolved_model == MODEL_NAME. (2) confirmed live that Groq tracks the
     6,000 tokens/minute budget per-model, not per-account (a same-second
     probe showed qwen/qwen3-32b at 1000 req/6000 tok vs
     llama-3.1-8b-instant at a separate 14400 req/6000 tok, decrementing
     independently) — `_remaining_tokens`/`_reset_at_monotonic` changed
     from single globals to dicts keyed by resolved model name.
     Verified: full suite 52 passed (42 prior − 1 removed stub test +
     10 new verifier.py tests + 1 new Developer-cache test), `ruff check
     backend/` clean. Beyond the automated suite, ran one real end-to-end
     scan against real Groq (not LLM_MOCK) on a local missing_alt.html
     page: Developer proposed a real fix, Verifier applied it via real
     Playwright DOM mutation and confirmed `verification_status=verified,
     retry_count=0` after a real detect_violations() rerun found the
     violation gone with nothing new introduced; Impact's call in that
     same run really did route to llama-3.1-8b-instant; a repeat Reviewer
     call on the same page really did hit the cache. cost_report.py's
     compute_agent_cost_summary(), run against the real (cumulative,
     historical) dev-DB llm_call_logs/fixes tables — not a clean isolated
     before/after benchmark, but genuinely logged data, not invented:
     Reviewer 188 calls (35.6% cache-hit rate), Impact 102 calls (models
     now include both qwen/qwen3-32b and llama-3.1-8b-instant, reflecting
     the mid-history model-routing change), Developer 94 calls, fixes:
     128 pre-Phase-3 rows still `verification_status` unset (as expected —
     nothing wrote it before this phase) plus 1 real `verified` row from
     this phase's own manual run, retry rate 0.0. A controlled before/after
     A/B benchmark (same site, pre- vs post-Phase-3 code) is a reasonable
     next step for a resume-quality cost-savings number, but wasn't
     required to close this phase's own checkboxes, which only require the
     numbers be real and logged — confirmed they are. -->
<!-- 2026-07-10: Phase 4 complete — dashboard + verified fixed-page
     delivery, real PyGithub PR deferred to optional Phase 6 (see design.md
     Section 11 for full reasoning, resolved collaboratively before any
     code was written this phase): most scanned sites aren't GitHub repos
     at all, so a generic "Approve & Open PR" button had nothing real to
     push to. The real deliverable instead: approve fixes on a page (per-
     fix grain, matching the existing schema) → combine every approved,
     individually-verified fix onto one copy of the page → full detector
     reruns once on the combined result → download if clean.

     Four planning-time decisions, each resolved and written into design.md
     before implementation (not silently assumed): (1) live-page drift
     between verification and generation, resolved by combining fixes
     against the page's already-captured raw_html_snapshot_path
     (`page.set_content()`) rather than a fresh live reload — proven
     directly by a test whose page_url points at a domain that would fail
     to resolve if ever fetched, and combination still succeeds; (2) partial
     approval explicitly allowed, not blocked, with the API response always
     reporting fixes_included_count/fixes_pending_count and the frontend
     button label reading directly from it; (3) CORS scoped to a real
     FRONTEND_ORIGIN setting, never a wildcard; (4) an "accessibility score"
     definition introduced for the first time (open_violations/page_count
     per scan, trended by completed_at) since nothing in schema.md defined
     one before.

     One correctness hardening done as an explicit prerequisite (not
     silently bundled): html-has-lang/html-lang-valid's target_selector is
     the whole `<html>` element — before this phase, "fixing" it the same
     way every other rule is fixed (full outerHTML replacement) would have
     forced the Developer LLM to regenerate the entire page for one
     attribute (real truncation risk) and would have silently overwritten
     every other already-applied fix once fixes started being combined onto
     one page. Fixed via a shared `verifier.apply_fix_to_locator()` helper
     (reused by both the existing per-fix verify_fix() and the new
     page_fixer.py combiner) that special-cases these two rule IDs to a
     targeted `setAttribute('lang', ...)` call; Developer's rule guidance
     changed to return only the bare language code for these two rules, not
     markup. Regression-proven combined with an unrelated fix on the same
     page (test_page_fixer.py), not just in isolation.

     Backend: html-lang hardening + 3 new lang-rule tests (verifier.py);
     Alembic migration 06c057e5a1fc adding 4 nullable Page columns
     (fixed_html_snapshot_path, combined_verification_status,
     combined_verification_detail, combined_verified_at), applied to dev
     DB live (confirmed via psql: all 4 present, all NULL on existing rows,
     5 sites/17 scans unchanged); new flat module page_fixer.py (same own-
     Playwright-lifecycle convention as detector.py/verifier.py) + 9 tests;
     5 new API endpoints (GET /sites, GET /scans, POST /fixes/{id}/approval,
     POST /pages/{id}/generate-fixed-page, GET /pages/{id}/download-fixed)
     + CORSMiddleware + 12 new tests, including one proving GET /scan/{id}
     reflects the *latest* Approval decision per fix (added a
     latest_approval_decision field main.py computes via a separate query,
     since Approval has no relationship() defined on Fix — models.py's own
     comment invited this when actually needed); cost_report.py extended
     with scan-performance and accessibility-score-trend queries + latency/
     success-rate added to the existing per-agent breakdown, wired to a new
     GET /performance/summary endpoint, + 6 new tests. Final count: 81
     backend tests passing (52 at Phase 3 close + 29 new), `ruff check`
     clean throughout — confirmed after every step, not just once at the
     end.

     Frontend: first frontend code in this project. Vite + React +
     TypeScript scaffold; `react-diff-viewer` substituted for
     `react-diff-viewer-continued` (same API, actively-maintained fork) —
     the original is unmaintained and its React 15/16 peer-dep genuinely
     fails to install against React 19, confirmed via a real `npm install`
     ERESOLVE error, not assumed. Three views (Violations, System
     Performance, Review & Approve) sharing a `useScanSelector` hook;
     System Performance's charts followed the dataviz skill's procedure for
     real (color-last, single sequential hue for magnitude, thin marks,
     hover tooltips, no legend needed for single-series charts) rather than
     picking colors first.

     Live-verified in a real browser via Playwright (chromium-cli wasn't
     available; adapted the skill's fallback pattern using the Python
     Playwright already in this project's venv), not just `tsc`/`vite
     build` passing: seeded real Violation/Fix rows into the dev DB (bypass
     LLM_MOCK's known limitation — mock Developer output's
     target_selector="mock-selector" can never actually verify against a
     real page, so a mock /scan can't produce real "verified" fixes to
     review), then drove the actual golden path (approve → generate →
     download button appears, confirmed via a real GET that returns the
     combined HTML with the real fix applied) and the violations_remain
     edge case (approve a fix that doesn't really fix anything → no
     download button, confirmed via a 0 count, not just "didn't crash").
     Zero browser console errors throughout. Found and fixed two real
     layout bugs this way, not shipped unnoticed: the bar chart's x-axis
     labels collided ("ImpactDeveloper" running together) because bars were
     spaced by their own width instead of equal category slots; the diff
     viewer overflowed its card and the page's own viewport width, fixed
     with a scoped overflow-x:auto wrapper + min-width:0 on the grid
     column (a CSS-grid default that otherwise lets wide content grow the
     track past its fair share). Demo rows deleted afterward via a scoped,
     pre-confirmed-URL-pattern cleanup script — dev DB back to exactly 5
     sites/17 scans, verified via psql before and after.

     Containerization completed for real, not just extended as the plan
     assumed: neither backend/ nor frontend/ had a Dockerfile before this
     phase — only Postgres was containerized, despite CLAUDE.md's stated
     "frontend + backend + Postgres only" scope. Added backend/Dockerfile
     (Python 3.14, `playwright install --with-deps chromium` matching
     ci.yml's own step exactly, an entrypoint running `alembic upgrade
     head` before serving) and frontend/Dockerfile (`vite preview`,
     VITE_API_BASE_URL baked in at build time as the host-browser-reachable
     `http://localhost:8000`, deliberately not the Docker-internal service
     name). Both images built and run live via `docker compose up`, not
     just `docker build` — real bug caught and fixed during this
     verification, not a hypothetical: a leftover local `vite dev` process
     (a genuinely separate Windows process invisible to this session's bash
     `ps`, only found via `netstat`/`tasklist`) was still bound to
     `[::1]:5173`, which `curl localhost`/a browser resolves to ahead of
     Docker's `0.0.0.0` proxy — so an early check appeared to hit the
     container but was actually still hitting stale dev-mode HMR output.
     Killed via `taskkill`, re-verified the container's own `dist/
     index.html` (confirmed via `docker exec`) matches what's actually
     served, then re-ran the Playwright smoke test against the real
     containerized pair (frontend container → backend container, the one
     new variable containerization introduces) — 0 console errors,
     confirming CORS/VITE_API_BASE_URL wiring genuinely works, not just
     that each container independently serves something. Backend+frontend
     containers stopped after verification (not left running unattended);
     Postgres left exactly as it was found.

     Not done this phase, deliberately: real PyGithub PR creation (Phase 6,
     optional); frontend automated test suite + CI extension (Phase 4.5,
     already a placeholder in PLAN.md, now real work instead of
     speculative now that frontend code actually exists); full SPA-
     hydration-safe standalone redeployment of the downloaded fixed page
     (documented limitation, design.md Section 11, same treatment as
     BackgroundTasks' non-durability). -->
<!-- 2026-07-10: Phase 4 follow-up — a loose end from pre-implementation
     review closed out. raw_html_snapshot_path has been nullable since
     Phase 1 (only set for status="loaded" pages), and page_fixer.py is a
     new, second consumer of that column beyond its original use; the
     null-handling case was never explicitly tested or mentioned in the
     completion report. main.py's generate_fixed_page endpoint already
     guarded against it (400), but page_fixer.py itself did not — its
     `except OSError` around Path(raw_html_snapshot_path).read_text(...)
     does not catch the TypeError Path(None) actually raises, confirmed
     directly (not just reasoned about) via a standalone
     `Path(None).read_text()` repro. This broke page_fixer.py's own
     documented "never raises" contract for that one input if the module
     were ever called without main.py's guard in front of it. Fixed with
     an explicit null/empty check before constructing a Path at all, plus
     two new real tests (module-level: direct call with
     raw_html_snapshot_path=None returns a structured error, not an
     exception; endpoint-level: a page with status="loaded" and a null
     snapshot path returns a clean 400) — 83/83 passing, `ruff check`
     clean. design.md Section 11 and PHASE4_COMPLETION_REPORT.md updated
     to document this as closed, not silently patched. -->
<!-- 2026-07-10: Phase 4.5 complete — frontend testing + CI/CD, worked in
     four checkpoints on a `phase-4.5` branch (not main), each committed
     and pushed before starting the next rather than batched at the end.

     Tooling: Vitest + React Testing Library, no MSW — mirrors the
     backend's own preference (design.md Section 10) for monkeypatching
     the real seam (api/client.ts's exports, or the useScanSelector hook
     directly for page tests) over a heavier mocking framework. Config
     kept separate (vitest.config.ts, not merged into vite.config.ts) and
     tests colocated (Component.test.tsx next to Component.tsx, not a
     mirrored tests/ tree) — both explicit decisions, not defaults picked
     without thought. Full reasoning in design.md Section 12.

     Checkpoint 1: vitest/RTL/jsdom tooling + setupTests.ts + tests for
     StatusBadge/TrendLineChart/BarChart/ViolationDiff (18 tests). Found
     and fixed a real setup gap along the way: with globals:false, RTL's
     auto-cleanup never self-registers, so every test after the first in
     a file saw leftover DOM from prior tests until an explicit
     afterEach(cleanup) was added.

     Checkpoint 2: a real production bug found and fixed, not just a
     testing gap (R1) — useScanSelector.ts's site->scans effect and
     refetchScan both fired a fetch with no check that a resolving
     response still matched the current selection; rapid reselection
     could let a stale response silently overwrite newer state. Grepped
     frontend/src first to confirm zero existing guards, then fixed
     before writing the test that would otherwise have locked in the bug.
     Landed as its own commit (5fb7783), separate from every test file,
     called out explicitly per your instruction rather than folded
     silently into a nominally "add tests" phase. Then
     useScanSelector.test.ts (8 tests, including two dedicated stale-
     response regression tests) + client.test.ts (6 tests).

     Checkpoint 3: page tests for ViolationsView (10), PerformanceView
     (6), and ReviewApproveView (11, heaviest) — approvableViolations()
     filtering, approve/reject + bulk-approve wiring, Generate button
     label branching, and three dedicated tests locking down the
     download-link gate (combined_verification_status === "clean" only).

     Checkpoint 4: extended ci.yml with an independent `frontend` job
     (no Postgres/backend services), verified green on a real triggered
     run. Then the red/green regression proof, tightened per your
     instruction to capture the specific failing assertion, not just "CI
     went red": inverted ReviewApproveView.tsx's download-link gate on a
     real push, red run 29124818143 — exactly the 3 download-gating
     tests failed, all 9 other tests in that file and every other file
     stayed green, backend `test` job unaffected. Reverted (byte-clean
     via git diff against the pre-regression commit), green run
     29124965399.

     Branch-hygiene correction, caught mid-session: the R1 fix commit
     landed directly on local main before phase-4.5 existed (an
     oversight — should have branched first). Confirmed origin/main was
     untouched (git fetch + empty diff both directions) before creating
     phase-4.5 at that commit and moving local main back, both confirmed
     with you before running (branch pointer moves are treated as
     destructive by this session's tooling). Final commit order on
     phase-4.5 is R1-fix-first rather than interleaved with Checkpoint
     1's tooling commit — a deliberate choice to avoid a history-
     rewriting reset for what would have been a purely cosmetic
     reordering, confirmed with you.

     60/60 frontend tests passing, `tsc -b` clean, `oxlint` clean, `vite
     build` clean, both CI jobs green on the real pushed branch. Branch
     protection intentionally NOT touched yet (design.md Section 12
     Decision 6 — needs your explicit go-ahead) and no PR into main
     opened yet (per your instruction, only once this phase is fully
     done). design.md Section 12 and PHASE4_5_COMPLETION_REPORT.md
     written. One unrelated drive-by fix: design.md Section 11 ended
     with a stale "Full narrative in PHASE2_5_COMPLETION_REPORT.md" copy-
     paste leftover (should reference PHASE4_COMPLETION_REPORT.md) -
     corrected while adding Section 12 immediately after it. -->
