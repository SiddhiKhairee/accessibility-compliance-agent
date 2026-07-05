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
- [ ] LangGraph workflow, exactly 4 nodes:
  - [ ] Reviewer Agent — confirms WCAG rule, confidence score
  - [ ] Impact Agent — URL-pattern heuristics first (/checkout /cart /login /payment), LLM only for ambiguous cases
  - [ ] Developer Agent — generates fix anchored to exact target CSS selector
  - [ ] Verifier Agent — see Phase 3
- [ ] Every agent call logs latency_ms, tokens_used, model_used, cache_hit (+confidence_score for Reviewer)
- [ ] **Deliverable:** violations carry WCAG confirmation, impact score+reasoning, proposed fix
- [ ] **Verify:** subagent review — confirm exactly 4 nodes, no scope creep

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
