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
- [ ] 2.5b — Phase 1 regression tests: detector unit tests against static
      fixture HTML with known, hand-verified violations (not live sites);
      crawler tests (same-domain restriction, max_pages/max_depth capping,
      skip+log-on-failure) against a local test server, not the real
      internet; API layer POST /scan → GET /scan/{id} round-trip against
      test DB
- [ ] 2.5c — Phase 2 regression tests: graph/node sequence in LLM_MOCK mode
      (Reviewer → Impact → Developer → Verifier); force a mock failure
      mid-graph, assert zero rows land in impact_assessments/fixes (the
      "no partial state" guarantee); cache_hit=true on repeated identical
      normalized input, plus explicit cases for normalization behavior
      (whitespace/tag-case only, never attribute values); is_mock/error_type
      logging — every call path writes a row, including failure paths
- [ ] 2.5d — CI/CD: `.github/workflows/ci.yml` — Postgres service
      container, Alembic upgrade, lint (ruff/black), pytest, on every push;
      CI green is the gate before Phase 3 work begins
- [ ] 2.5e — Verify & close: confirm the suite actually fails on an
      intentionally reintroduced bug (e.g. the datetime tz bug from Phase 1)
      — a suite that can't fail proves nothing; update CLAUDE.md/PLAN.md/
      design.md to reflect what was actually built
- [ ] **Deliverable:** a real pytest suite covering Phase 1+2 regressions,
      running in CI on every push, gating Phase 3
- [ ] **Verify:** CI is green on a clean run, and red when an intentional
      regression is reintroduced

## Phase 3 — Fix Verification + Cost Optimization
- [ ] Verification Agent applies fix locally at target selector, re-runs FULL detector
- [ ] Diff entire before/after violation set (not just the one flagged rule)
- [ ] Retry-once-then-manual_review logic with failure_reason enum
- [ ] Real cost optimization: cache repeated identical violation patterns, and/or route simple steps to smaller model
- [ ] Measure and log real before/after cost comparison
- [ ] **Deliverable:** verified/rejected/manual_review fixes with real failure reasons + real cost figure
- [ ] **Verify:** confirm cost numbers come from logged data, not estimates

## Phase 4 — Dashboard
- [ ] Violations view: sites/scans, prioritized violations, before/after diffs, verification status
- [ ] System Performance tab: throughput, pipeline time (median/p95), per-agent latency+success%, cache hit%, verification breakdown, scan success rate, PR metrics, accessibility score trend
- [ ] Review & Approve tab: side-by-side diff viewer + "Approve & Open PR" button (human click required)
- [ ] **Deliverable:** clickable fullstack demo — detection, reasoning, cost, approval end to end

## Phase 5 — Evaluation & Metrics
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
