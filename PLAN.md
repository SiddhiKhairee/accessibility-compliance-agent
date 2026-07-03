# PLAN.md — Accessibility Compliance Agent

Resume point: work top to bottom. Don't start a phase until the previous
phase's deliverable is checked off and verified.

## Phase 0 — Design & Scoping
- [ ] Lock v1 WCAG rule set: alt text, color contrast, missing form labels, keyboard-nav traps
- [ ] Define "critical path" criteria (checkout, login, primary forms) for the Impact Agent
- [ ] Draft design.md v0 with architecture diagram
- [ ] **Deliverable:** design.md draft + locked scope

## Phase 1 — Detection Engine + Non-Blocking API
- [ ] Playwright crawler + axe-core detector
- [ ] FastAPI endpoint returns scan_id immediately, runs crawl/detect via BackgroundTasks
- [ ] GET /scan/{id} status endpoint for polling
- [ ] Document BackgroundTasks limitation in design.md
- [ ] Defensive crawling: timeouts, skip+log failures, exclude authenticated pages
- [ ] **Deliverable:** API that accepts a URL, scans async, returns structured violations
- [ ] **Verify:** run against 2-3 real public URLs, confirm structured output

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
