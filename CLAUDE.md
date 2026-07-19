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
- LLM: `qwen/qwen3.6-27b` via Groq's free-tier API (`reasoning_format:
  "hidden"`, `response_format: {"type": "json_object"}`). Changed from the
  original local-via-Ollama plan in Phase 2 planning: this machine has only
  ~2.2GB RAM free of 16GB, making a local 7B+ model a real swap-thrashing
  risk alongside Docker/Postgres/Playwright. Genuinely free (no card,
  verified against Groq's own docs), but is a third-party API — page
  HTML/violation content leaves the machine. Full reasoning logged in
  `C:\Users\siddh\.claude\plans\delegated-sniffing-lollipop.md`. Real-call
  rate-limit pacing lives in `llm_client.py` — an adaptive/reactive sleep
  plus a fixed per-model minimum delay layered on top (design.md Sections
  8b and 14d; the fixed delay was added after Phase 5 Pass 1b Session 1
  showed the reactive-only version wasn't enough at sustained scale).
  Switched from `qwen/qwen3-32b` on 2026-07-19 after Groq removed it from
  their catalog entirely (a real call returned HTTP 404 `model_not_found`
  mid-Pass-1b-resume, not a rate-limit issue) — see `llm_client.py`'s
  `MODEL_NAME` comment and design.md Section 14g for the live verification
  and the resulting two-model-version caveat on the Phase 5 eval corpus.
- Evaluation pipeline (Phase 5): `eval_runner.py` runs Pass 1a (crawl +
  detect, free) then Pass 1b (Reviewer-only confidence scoring, real Groq
  calls, budget-gated) against `eval/eval_corpus_30_sites.csv`.
  `eval_sampling.py` draws a stratified sample of Pass 1b's results for
  Pass 2 (Impact→Developer→Verifier fix-quality spot-check — sampler
  exists, the run orchestrator doesn't yet). `eval_report.py` computes the
  real metrics. See PLAN.md's Phase 5 section and design.md Sections
  13/14 for current real status — don't assume any of these have finished
  a full corpus run without checking.
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
- Real (non-mock) Groq calls spend a shared, finite daily budget
  (`EVAL_DAILY_CALL_CAP`, see design.md Section 9). Never trigger a real
  eval run (Pass 1b, Pass 2) or a real production scan as a side effect of
  unrelated work — confirm with the user first if spending real API budget
  isn't the explicit task at hand.

## Known/intentional limitations (keep documented in design.md, don't silently fix)
- FastAPI BackgroundTasks is in-process: doesn't survive server restart, no
  real retry/queue visibility. Note Redis-backed queue as the natural next
  step rather than pretending this isn't a limitation.

## Conventions
- Every agent node's prompt + output schema lives in `agents/<name>/`.
- DB schema changes go through a migration, never hand-edited in prod.
- Commit messages: `phase-N: <what>` while working through PLAN.md phases.
- Never add a `Co-Authored-By: Claude` trailer to commits in this repo. This
  is a portfolio/job-search project — the trailer previously caused "Claude"
  to show up in the GitHub Contributors graph, which read as a risk for a
  recruiter reviewing the repo, and had to be amended + force-pushed out.
- Every commit goes through a feature branch + PR, never a direct commit
  onto local/remote `main`: branch → commit → push → `gh pr create` → wait
  for CI (`test`/`frontend`) green → let the user merge. `main` has real
  branch protection (required status checks, force-push/deletion blocked),
  and this repo has been caught out twice by a fix landing directly on local
  `main` by oversight. Branch creation is an assumed first step for any
  commit here, not something to ask permission for separately.

## Workflow
- Follow PLAN.md phase order strictly — Phase 1's detection engine must be
  solid before Phase 2's multi-agent layer; Phase 2.5's automated test
  suite + CI must be green before Phase 3's real fixes are built (Phase 3
  is the highest-risk, most regression-prone code so far); Phase 3's real
  fixes must exist before Phase 4's approval UI.
- Start each phase in Plan Mode. Confirm the approach before writing code.
- After finishing a phase: update PLAN.md checkboxes, run tests, then `/clear`
  before starting the next phase's planning.
