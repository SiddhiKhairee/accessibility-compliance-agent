# Accessibility Compliance Agent — CLAUDE.md

## What this is
Agentic system that crawls public websites, detects WCAG violations, runs a
4-node LangGraph workflow to reason about + fix them, verifies fixes locally,
and requires human approval before opening a real GitHub PR.

## Tech stack (do not substitute without asking)
- Crawling: Playwright (Python)
- Detection: axe-core via Playwright
- Agent orchestration: LangGraph — exactly 4 nodes: Reviewer, Impact,
  Developer, Verifier. Do not add a 5th node without an explicit, distinct
  responsibility — node-count bloat is the failure mode to avoid here.
- LLM: `qwen/qwen3-32b` via Groq's free-tier API (`reasoning_format:
  "hidden"`, `response_format: {"type": "json_object"}`). Changed from the
  original local-via-Ollama plan in Phase 2 planning: this machine has only
  ~2.2GB RAM free of 16GB, making a local 7B+ model a real swap-thrashing
  risk alongside Docker/Postgres/Playwright. Genuinely free (no card,
  verified against Groq's own docs), but is a third-party API — page
  HTML/violation content leaves the machine. Full reasoning logged in
  `C:\Users\siddh\.claude\plans\delegated-sniffing-lollipop.md`.
- Backend: FastAPI + BackgroundTasks (non-blocking scan endpoint)
- DB: PostgreSQL — schema is fixed, see `docs/schema.md` (do not add
  orgs/users/multi-tenancy — no real concurrent users to justify it)
- Frontend: React + TypeScript
- Diff viewing: react-diff-viewer
- GitHub integration: PyGithub (not raw REST calls)
- Containerization: Docker / Docker Compose (frontend + backend + Postgres only)
- CI: GitHub Actions — lint (ruff) + full pytest suite, on every push (any
  branch) and PRs into `main`. Real and enforced as of Phase 2.5's close
  (`.github/workflows/ci.yml`, merged via PR #11) — not aspirational.
  `main` has branch protection requiring the `test` check to pass before
  merging. Verified via real triggered Actions runs, including a
  deliberate regression proof (PR #12): red on a real reintroduced bug,
  green after reverting. See PHASE2_5_COMPLETION_REPORT.md.

## Hard rules
- No fix ever reaches a PR without an explicit human "Approve & Open PR" click.
  Never build or suggest a fully-automatic PR path.
- Every LLM/agent call must log: latency_ms, tokens_used, model_used,
  cache_hit (Reviewer also logs confidence_score). This is not optional
  instrumentation — the System Performance dashboard depends on it.
- Verification Agent must re-run the FULL detector on the whole page after a
  fix, not just re-check the single flagged rule. A fix is "verified" only if
  the original violation is gone AND no new violation appeared.
- If a fix fails to apply or fails verification: retry once automatically,
  then mark `manual_review` with a `failure_reason` (invalid_html,
  dom_changed, playwright_timeout, diff_failed_to_apply). Never silently drop
  a failure or claim a fix works without passing verification.
- Defensive crawling: per-page timeouts; skip + log pages that fail to load
  rather than crashing the whole scan. Authenticated pages are out of v1 scope.
- Any real number that ends up in EVALUATION.md or a resume bullet must be
  traceable to actual logged data — never invent or round-up metrics.

## Known/intentional limitations (keep documented in design.md, don't silently fix)
- FastAPI BackgroundTasks is in-process: doesn't survive server restart, no
  real retry/queue visibility. Note Redis-backed queue as the natural next
  step rather than pretending this isn't a limitation.

## Conventions
- Every agent node's prompt + output schema lives in `agents/<name>/`.
- DB schema changes go through a migration, never hand-edited in prod.
- Commit messages: `phase-N: <what>` while working through PLAN.md phases.

## Workflow
- Follow PLAN.md phase order strictly — Phase 1's detection engine must be
  solid before Phase 2's multi-agent layer; Phase 2.5's automated test
  suite + CI must be green before Phase 3's real fixes are built (Phase 3
  is the highest-risk, most regression-prone code so far); Phase 3's real
  fixes must exist before Phase 4's approval UI.
- Start each phase in Plan Mode. Confirm the approach before writing code.
- After finishing a phase: update PLAN.md checkboxes, run tests, then `/clear`
  before starting the next phase's planning.
