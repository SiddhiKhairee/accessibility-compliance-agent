# schema.md — Accessibility Compliance Agent DB Schema

This schema is intentionally scoped to what will actually be populated
with real data — no orgs/users/multi-tenancy tables, since there are no
real concurrent users to justify it. Schema changes go through a
migration, never hand-edited in prod (see CLAUDE.md).

## sites
- `id`
- `url`
- `last_scanned_at`

## scans
- `id`
- `site_id`
- `status` (queued / running / done / failed)
- `started_at`
- `completed_at`

## pages
- `id`
- `scan_id`
- `url`
- `raw_html_snapshot_path` (nullable: only set for `status="loaded"` pages)
- `status` (nullable: "loaded" / "failed" — added so every crawled page gets
  a row, not just successful ones; Phase 4's scan-success-rate metric and
  Phase 5's evaluation numbers need this traceable to real logged rows,
  per CLAUDE.md's ban on invented metrics)
- `failure_reason` (nullable — populated when `status="failed"`)
- `fixed_html_snapshot_path` (nullable — Phase 4: path to the combined,
  verified-fixed HTML produced by `page_fixer.py` once a human approves at
  least one fix on this page and generation succeeds. See design.md's
  Phase 4 section for why this is applied to `raw_html_snapshot_path`'s
  frozen content rather than a fresh live reload.)
- `combined_verification_status` (nullable — "clean" / "violations_remain" /
  "error". Plain String, not an enum, matching `severity`/
  `detection_confidence`'s precedent for an evolving vocabulary.)
- `combined_verification_detail` (nullable — short human-readable summary,
  e.g. partial-approval counts. Same spirit as `verifier.py`'s
  `VerifyAttemptResult.detail`.)
- `combined_verified_at` (nullable — stamped on any terminal outcome
  (clean/violations_remain/error alike), matching `fixes.verified_at`'s
  stamp-on-success-or-failure precedent.)
  **Rows written before this migration are `NULL` on all four columns, not
  backfilled** — same precedent as `violations.detection_confidence`.

## violations
- `id`
- `page_id`
- `wcag_rule`
- `element_selector`
- `severity`
- `confidence`
- `status` (open / fixed / rejected)
- `html_snippet` (nullable — added because detector.py already produces this
  and Phase 2's Developer Agent needs it without re-deriving it from the raw
  HTML snapshot)
- `message` (nullable — added for the same reason as `html_snippet`)
- `detection_confidence` (nullable — Phase 2.6: "confirmed" for a normal
  axe `violations` result, or "needs_review" for the 2 `reviewOnFail` rules
  (`bypass`, `duplicate-id-aria`) whose real failures land in axe's
  `incomplete` array instead — see design.md Section 3. **Rows written
  before this column existed are `NULL`, not `"confirmed"` — no backfill
  is planned.** A `WHERE detection_confidence = 'confirmed'` query or
  dashboard filter must account for `NULL` or it will silently drop every
  pre-migration row.)

## impact_assessments
- `id`
- `violation_id`
- `is_critical_path` (bool)
- `reasoning_text`
- `business_risk_score`

## fixes
- `id`
- `violation_id`
- `proposed_code_diff`
- `target_selector`
- `verification_status` (verified / rejected / manual_review — `rejected`
  means the fix applied and the full detector reran cleanly, but the
  violation persisted or a new one appeared; `manual_review` means a
  technical failure, e.g. timeout/invalid HTML/selector not found,
  persisted through the one automatic retry)
- `failure_reason` (nullable: invalid_html, dom_changed, playwright_timeout,
  diff_failed_to_apply — only ever set alongside `manual_review`, never
  alongside `rejected`)
- `retry_count` (0 or 1 — Phase 3's retry is mechanical only: the same
  proposed fix re-attempted against a freshly reloaded page, no new
  Developer LLM call)
- `verified_at` (Phase 3: stamped whenever the Verifier reaches ANY
  terminal verdict — verified, rejected, or manual_review alike — not only
  on a positive result. Matches this schema's own `scans.completed_at`
  precedent of stamping on success or failure.)

## approvals
- `id`
- `fix_id`
- `approver`
- `decision` (approved / rejected)
- `decided_at`
- `pr_url` (nullable)
- `pr_status` (created / merged / rejected / pending)

## llm_call_logs
- `id`
- `agent_name` (Reviewer / Impact / Developer / Verifier)
- `latency_ms`
- `tokens_used`
- `model_used`
- `cache_hit` (bool)
- `confidence_score` (nullable, Reviewer only)
- `created_at`
