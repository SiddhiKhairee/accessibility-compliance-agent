# Phase 2.5 Completion Report — Automated Test Suite + CI/CD Pipeline (2.5a-e)

Built across five sub-phases (2.5a-e), each in its own Plan Mode session
per CLAUDE.md's workflow rule. This report covers all five as one
narrative. Numbers for 2.5a-d are cited from PLAN.md's existing session
log (built and verified in those earlier sessions, not re-run from
scratch here); numbers for 2.5e are freshly confirmed in this session —
both are labeled accordingly throughout, per CLAUDE.md's no-invented-
metrics rule.

## 1. What was built, sub-phase by sub-phase

| Sub-phase | Deliverable |
|---|---|
| 2.5a | Test infrastructure: pytest + pytest-asyncio, a fully separate test Postgres (`postgres_test`, profile-gated in `docker-compose.yml`, port 5434), Alembic run against it via a session-scoped autouse fixture, `.env.test` forcing `LLM_MOCK=true` |
| 2.5b | 28 tests: 17 detector fixture tests, 8 crawler tests (local HTTP server, never the real internet), 1 API round-trip test, +2.5a's 2 infra-smoke tests |
| 2.5c | 13 more tests (41 total): graph/node-sequence tests, the "no partial state on mid-graph failure" test, 3 Reviewer-cache tests, 6 error-classification tests |
| 2.5d | `.github/workflows/ci.yml` — real CI, verified via actual triggered Actions runs, not just YAML review |
| 2.5e | This report + PLAN.md/design.md/CLAUDE.md closure, one consolidated CI-level regression proof, branch protection on `main` |

## 2. Real dependency/tooling decisions (cited from PLAN.md's 2.5a-d session log)

- **Test DB**: profile-gated `postgres_test` service in the existing
  `docker-compose.yml` (not a `docker-compose.override.yml`, since that
  file is gitignored and wouldn't be shared via git), port 5434, distinct
  `accessibility_agent_test` database.
- **Migrations**: a one-line conditional guard added to
  `migrations/env.py` (`if not config.get_main_option("sqlalchemy.url"):`)
  so a caller-set `sqlalchemy.url` isn't clobbered back to dev, letting a
  session-scoped autouse pytest fixture run the real Alembic chain
  against the test DB instead of a hand-built schema.
- **Mock strategy**: `LLM_MOCK=true` forced via `.env.test`;
  `llm_client.py`'s `_call_mock`/`_call_real` dispatch is monkeypatched
  at the function level in tests that need to force a single-node
  failure (`graph/test_partial_state.py`) — `call_llm()` resolves
  `_call_mock` as a same-module global at call time, so patching the
  module attribute works with zero edits to `llm_client.py` itself.
- **`ruff`** (2.5d), zero custom config — `ruff check backend/`'s
  built-in default rule set was sufficient; it surfaced exactly one real
  finding across the entire pre-2.5d codebase.
- **`gh` CLI**, installed and authenticated mid-2.5d-session, used
  throughout 2.5d/e for real Actions-run verification (`gh run watch`/
  `gh run view --log`), not just local YAML inspection.

## 3. The `bypass`/`duplicate-id-aria` detector gap (discovered during 2.5b)

Found by accident during 2.5b fixture verification, not a full audit:
`bypass` and `duplicate-id-aria` are marked `reviewOnFail: true` in
axe-core's own rule metadata, so a genuine failure of either lands in
axe's `incomplete` result array, not `violations`. `detector.py`'s
`detect_violations()` only reads `violations`, so neither of these 2
locked v1 rules can ever produce a `Violation` row under the current
implementation — confirmed directly by running raw axe calls against
fixtures that genuinely fail each rule. Codified as known-gap regression
tests (`test_bypass_known_gap_never_surfaces_as_a_violation`,
`test_duplicate_id_aria_known_gap_never_surfaces_as_a_violation`) rather
than fixed in 2.5b — out of scope for a regression-test session. Full
detail in design.md Section 3; tracked as **Phase 2.6** in PLAN.md
(backlog, not started) — only 2 of the 9 locked rules were checked for
this gap, by accident, so Phase 2.6 starts with auditing all 9 before
deciding a fix.

## 4. The lint-fix exception (2.5d)

Adding `ruff` and running it against the whole pre-existing `backend/`
tree (per your explicit direction) surfaced one real finding: an unused
`import pytest` in `backend/tests/crawler/test_crawler.py` — a 2.5b file,
which this phase's own hard constraint said not to touch. You explicitly
approved fixing it anyway as a named exception: one line, zero behavior
risk, and blocking CI's own lint gate otherwise. Fixed; full suite
re-confirmed 41 passed immediately after.

## 5. The mid-2.5d CI failure, found and fixed live (not anticipated in planning)

First real CI run (PR #11, not the deliberate red-run proof) failed
unexpectedly: `test_scan_roundtrip.py`'s isolation check reads
`backend/app/.env` (the **dev** config file) directly via
`dotenv_values()` — a raw file parse, bypassing `os.environ` entirely —
to prove a scan never touched the dev DB. That file is gitignored and
doesn't exist in a fresh CI checkout, so the check's own
`assert dev_database_url is not None` failed.

Root-caused and fixed without touching that test file: switched from
job-level env vars (the original design) to writing real `.env`/
`.env.test` files in CI, backed by **two** Postgres services mirroring
`docker-compose.yml` exactly (5433 dev, 5434 test — not just one), with
Alembic applied to *both* databases, since the isolation check queries a
real `sites` table on the dev DB (needing the schema present, not just
the database to exist). Full reasoning in design.md Section 10.

## 6. This session's fresh verification (2.5e)

**Full local suite, run fresh at the start of this session:**
```
======================== 41 passed in 83.84s (0:01:23) ========================
```
Matches 2.5d's last known-good count exactly — no drift.

**`main`'s post-merge CI run** (triggered by PR #11's squash-merge,
`7598387`): run `28919812633`, `conclusion: "success"`.

**Branch protection**: confirmed via `gh api .../branches/main/protection`
that none existed before this session (`404 "Branch not protected"`).
After your explicit go-ahead, added via:
```
gh api repos/SiddhiKhairee/accessibility-compliance-agent/branches/main/protection -X PUT --input -
{
  "required_status_checks": {"strict": true, "checks": [{"context": "test"}]},
  "enforce_admins": true, "required_pull_request_reviews": null,
  "restrictions": null, "allow_force_pushes": false, "allow_deletions": false
}
```
Verified active: `{"allow_force_pushes":false,"contexts":["test"],"enforce_admins":true,"strict":true}`.

## 7. The consolidated "does Phase 2.5 actually protect Phase 3" proof

Reintroduced the real Phase 1 datetime-tz bug
(`PHASE1_COMPLETION_REPORT.md` Section 5.2) — `models.py`'s `_TZ_DATETIME`
reverted to `DateTime(timezone=False)`, plus a throwaway Alembic migration
altering `scans.started_at`/`completed_at` back to
`TIMESTAMP WITHOUT TIME ZONE` — on a real PR (#12), and proved the actual
CI pipeline (fresh ephemeral Postgres, full Alembic chain, full pytest
run) catches it end to end. Distinct from every individual proof already
done in 2.5b/c/d (which either ran locally or used a lint violation): this
is a real historical application bug, caught by the real deployed CI
gate, not a local pytest invocation.

**Quick local sanity check first** (to avoid burning CI minutes on a
typo, not the official proof): reproduced the exact original error
locally —
```
DataError("invalid input for query argument $2: datetime.datetime(2026, 7, 8, 5, 41, 31,...
(can't subtract offset-naive and offset-aware datetimes)")
```
— then fully reverted (downgraded the local test DB, deleted the
migration, reverted `models.py`) before touching git at all.

**Real CI red** (run `28920503993`, PR #12): `conclusion: "failure"`.
**A genuinely broader blast radius than anticipated in planning** — the
plan expected only `test_scan_roundtrip.py` to fail (the test that
originally surfaced this bug in Phase 1). The real result was
**12 failed, 29 passed**, because `_TZ_DATETIME` is a single shared
constant used by *every* timestamp column across `models.py`
(`sites.last_scanned_at`, `scans.started_at`/`completed_at`,
`fixes.verified_at`, `approvals.decided_at`, `llm_call_logs.created_at`,
`llm_response_cache.created_at`) — reverting it broke every write path
touching any of them, not just the one migration this session explicitly
altered. Confirmed directly from the real generated SQL in the CI log:
```
INSERT INTO llm_call_logs (..., created_at, ...) VALUES (..., $7::TIMESTAMP WITHOUT TIME ZONE, ...)
```
— SQLAlchemy renders the parameter cast from the ORM-side type annotation,
not the live database column, so every model using `_TZ_DATETIME` was
affected regardless of which migration this session touched. All 12
failures were the identical real error
(`asyncpg.exceptions.DataError: ... can't subtract offset-naive and
offset-aware datetimes`), not 12 different bugs — reported honestly as
the real, wider number rather than the narrower one originally assumed.

**Real CI green after revert** (run `28920679468`, same PR): `conclusion:
"success"`, **41 passed**. `git diff`/`git diff --stat` against the
pre-regression commit confirmed empty before pushing the revert — same
explicit clean-revert standard 2.5c/2.5d established. PR #12 closed
without merging (nothing to merge — branch was byte-identical to `main`)
and the branch deleted.

## 8. What's explicitly NOT done (deferred, not forgotten)

- **Phase 2.6** (detector `reviewOnFail` audit/fix) — backlog, not
  started, tracked separately in PLAN.md.
- **No frontend CI** — no frontend code exists yet (Phase 4).
- **No lint beyond ruff's built-in defaults** — no `ruff.toml`/
  `pyproject.toml`, no `black` despite CLAUDE.md's original "ruff/black"
  phrasing; ruff alone was sufficient for the one real finding surfaced.
- **No re-verification of every individual 2.5a-c proof this session** —
  this session re-ran the full suite fresh (Section 6) and added one new
  consolidated CI-level proof (Section 7); it did not re-derive 2.5b's
  detector-gap fixtures or 2.5c's local partial-state proof from scratch.

## 9. Real final state

- `main` at `7598387` (PR #11's squash-merge) plus this session's doc
  commits.
- CI green on `main` (run `28919812633`, re-confirmed by every
  subsequent push/PR this session).
- Branch protection active on `main`, requiring the `test` check.
- 41 real pytest tests, 0 skipped, 0 xfailed — the number is exact, not
  rounded.
- Phase 2.5 fully closed. Phase 3 (real fix-application + reverification,
  "the highest-risk, most regression-prone code so far" per PLAN.md) is
  now gated by a real, proven-to-fail, proven-to-recover CI pipeline.
