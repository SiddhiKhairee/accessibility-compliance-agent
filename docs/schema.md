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
- `raw_html_snapshot_path`

## violations
- `id`
- `page_id`
- `wcag_rule`
- `element_selector`
- `severity`
- `confidence`
- `status` (open / fixed / rejected)

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
- `verification_status` (verified / rejected / manual_review)
- `failure_reason` (nullable: invalid_html, dom_changed, playwright_timeout, diff_failed_to_apply)
- `retry_count`
- `verified_at`

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
