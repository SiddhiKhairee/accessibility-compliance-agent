# Phase 1 Completion Report — FastAPI + Postgres layer

Built fully autonomously overnight per the approved plan
(`C:\Users\siddh\.claude\plans\spicy-puzzling-flurry.md`). **PLAN.md was
deliberately left untouched** — checkbox updates and the session-log entry
wait for your review below.

## 1. Dependency check (Step 0 gate)

| Dependency | Status before | Action |
|---|---|---|
| Docker Desktop | Installed but **daemon not running** | Started it (`Start-Process`), waited for `docker info` to succeed (~2 min) |
| Docker Compose | v2.40.2-desktop.1, present | none needed |
| `sqlalchemy[asyncio]` | absent | installed `2.0.51` |
| `alembic` | absent | installed `1.18.5` |
| `asyncpg` | absent | installed `0.31.0` (confirmed real Windows/cp314 wheel, no source build) |
| `pydantic-settings` | absent | installed `2.14.2` |
| `python-dotenv` | absent | installed `1.2.2` (unpinned, resolved) |

`pip show pydantic` after install: still `2.13.4` — no version drift, so the
planned smoke-test-via-standalone-scripts fallback wasn't needed.

**The only genuine stop-condition candidate** was Docker's daemon being down.
It was resolvable within this session (no reboot/manual install needed), so
per the plan's "only stop if truly outside this session's ability to fix"
rule, I started it and proceeded rather than halting.

## 2. Files created/changed

New: `backend/app/config.py`, `backend/app/db.py`, `backend/app/main.py`,
`backend/app/models.py`, `backend/app/.env` (gitignored) /
`backend/app/.env.example`, `backend/app/api_standalone_test.py`,
`backend/alembic.ini`, `backend/migrations/` (env.py + one revision),
`docker-compose.yml`.
Updated: `requirements.txt`, `docs/schema.md`, `design.md`.
**Not touched:** `PLAN.md` (per instructions).

## 3. Initial Alembic migration (final content, post-fixes)

Revision `f2c8003c7e94`, "initial schema: 8 tables per docs/schema.md" —
autogenerate got table creation order right on the first pass (FK-dependency
safe: `llm_call_logs`, `sites`, `scans`, `pages`, `violations`, `fixes`,
`impact_assessments`, `approvals`). Two things were manually fixed after
autogenerate before this became the final version (see deviations below):
enum cleanup added to `downgrade()`, and all `DateTime()` columns changed to
`DateTime(timezone=True)`.

```python
"""initial schema: 8 tables per docs/schema.md

Revision ID: f2c8003c7e94
Revises:
Create Date: 2026-07-05 04:02:44.242467

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2c8003c7e94'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('llm_call_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('agent_name', sa.Enum('Reviewer', 'Impact', 'Developer', 'Verifier', name='agent_name'), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('tokens_used', sa.Integer(), nullable=False),
    sa.Column('model_used', sa.String(length=100), nullable=False),
    sa.Column('cache_hit', sa.Boolean(), nullable=False),
    sa.Column('confidence_score', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('sites',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('url', sa.String(length=2048), nullable=False),
    sa.Column('last_scanned_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sites_url'), 'sites', ['url'], unique=True)
    op.create_table('scans',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('queued', 'running', 'done', 'failed', name='scan_status'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('pages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('scan_id', sa.Integer(), nullable=False),
    sa.Column('url', sa.String(length=2048), nullable=False),
    sa.Column('raw_html_snapshot_path', sa.String(length=1024), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['scan_id'], ['scans.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('violations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('page_id', sa.Integer(), nullable=False),
    sa.Column('wcag_rule', sa.String(length=100), nullable=False),
    sa.Column('element_selector', sa.Text(), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('status', sa.Enum('open', 'fixed', 'rejected', name='violation_status'), nullable=False),
    sa.Column('html_snippet', sa.Text(), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['page_id'], ['pages.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('fixes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('violation_id', sa.Integer(), nullable=False),
    sa.Column('proposed_code_diff', sa.Text(), nullable=True),
    sa.Column('target_selector', sa.Text(), nullable=True),
    sa.Column('verification_status', sa.Enum('verified', 'rejected', 'manual_review', name='fix_verification_status'), nullable=True),
    sa.Column('failure_reason', sa.Enum('invalid_html', 'dom_changed', 'playwright_timeout', 'diff_failed_to_apply', name='fix_failure_reason'), nullable=True),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['violation_id'], ['violations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('impact_assessments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('violation_id', sa.Integer(), nullable=False),
    sa.Column('is_critical_path', sa.Boolean(), nullable=False),
    sa.Column('reasoning_text', sa.Text(), nullable=True),
    sa.Column('business_risk_score', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['violation_id'], ['violations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('approvals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('fix_id', sa.Integer(), nullable=False),
    sa.Column('approver', sa.String(length=255), nullable=True),
    sa.Column('decision', sa.Enum('approved', 'rejected', name='approval_decision'), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('pr_url', sa.String(length=1024), nullable=True),
    sa.Column('pr_status', sa.Enum('created', 'merged', 'rejected', 'pending', name='pr_status'), nullable=True),
    sa.ForeignKeyConstraint(['fix_id'], ['fixes.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('approvals')
    op.drop_table('impact_assessments')
    op.drop_table('fixes')
    op.drop_table('violations')
    op.drop_table('pages')
    op.drop_table('scans')
    op.drop_index(op.f('ix_sites_url'), table_name='sites')
    op.drop_table('sites')
    op.drop_table('llm_call_logs')

    # Manually added — see deviations section below.
    bind = op.get_bind()
    sa.Enum(name='agent_name').drop(bind, checkfirst=True)
    sa.Enum(name='scan_status').drop(bind, checkfirst=True)
    sa.Enum(name='violation_status').drop(bind, checkfirst=True)
    sa.Enum(name='fix_verification_status').drop(bind, checkfirst=True)
    sa.Enum(name='fix_failure_reason').drop(bind, checkfirst=True)
    sa.Enum(name='approval_decision').drop(bind, checkfirst=True)
    sa.Enum(name='pr_status').drop(bind, checkfirst=True)
```

Downgrade/upgrade round-trip was run twice (once before the datetime fix,
once after) — both times all 8 tables + all 7 enum types dropped and
recreated cleanly with no orphaned Postgres types.

## 4. Raw verification output

**Environment:** `docker compose up -d postgres` → healthy. `alembic upgrade
head` → 8 tables + `alembic_version` confirmed via `\dt`. Server started via
`cd backend/app && uvicorn main:app --port 8000`.

**Real-URL run** (`python api_standalone_test.py`, 3 URLs):
```
Submitted scans: {'https://www.usa.gov': 1, 'https://news.ycombinator.com': 2, 'https://example.com': 3}
scan 3: status=done pages=1 loaded=1 violations=0
scan 2: status=done pages=15 loaded=15 violations=530
scan 1: status=done pages=15 loaded=15 violations=1
```
Cross-checked directly in Postgres:
```
 scan_id |             url              | status  | pages | violations
---------+------------------------------+---------+-------+------------
       1 | https://www.usa.gov          | done    |    15 |          1
       2 | https://news.ycombinator.com | done    |    15 |        530
       3 | https://example.com          | done    |     1 |          0
```
Spot-checked persisted violation rows have real, non-null `html_snippet` and
`message` content (e.g. `color-contrast` violations on Hacker News rows carry
the actual `<span>`/`<a>` HTML and axe's contrast-ratio message text) — the
schema-gap addition is doing its job, not just present as empty columns.
No pages had a `detection_error` or `status="failed"` in this run (all 31
page loads across the 3 sites succeeded) — so this run doesn't independently
exercise the new `pages.status="failed"` path; that path was already
exercised in the pre-API standalone crawler proof against python.org
(documented in design.md Section 4b) and is structurally identical here
(same `CrawledPage.status`/`failure_reason` fields, just now persisted
instead of only logged).

**Kill-mid-scan test** (validates design.md Section 4f's limitation claim):
1. POSTed a 4th scan (usa.gov) → `scan_id=4`.
2. After 4s, confirmed via direct DB query: `status=running`,
   `started_at` set, `completed_at` null.
3. Force-killed the uvicorn process (`taskkill /F /PID <pid>`).
4. Restarted uvicorn fresh.
5. Re-queried scan 4 (both via DB and `GET /scan/4`) 8s after restart:
   still `status=running`, `completed_at` still null. Confirmed: nothing
   resumed or marked it failed. Matches the documented limitation exactly.
6. Checked for orphaned Playwright/Chromium processes after the kill — found
   none (`wmic ... CommandLine like '%ms-playwright%'` returned nothing);
   the chrome.exe processes present on the machine were all the user's own
   regular browser, correctly left alone.

Final state left running for your morning review: Postgres container
healthy, uvicorn serving on `:8000`, scan #4 intentionally left stuck at
`running` as live evidence of the documented limitation.

## 5. Deviations from the plan, and errors hit + fixes

1. **Port conflict (found, fixed):** `docker compose up` initially failed
   silently at the connection level — a pre-existing native Windows
   `postgres.exe` service (unrelated to this project) already owned port
   5432 on this machine, intercepting connections meant for the container.
   Fixed by remapping the container to host port **5433** in
   `docker-compose.yml` (`5433:5432`) and updating `DATABASE_URL` in both
   `.env` and `.env.example` accordingly. Did not touch or stop the other
   Postgres service — out of scope and not this project's to manage.
2. **Datetime bug (found, fixed):** first end-to-end run threw
   `asyncpg.exceptions.DataError: ... can't subtract offset-naive and
   offset-aware datetimes` on every `POST /scan` — `main.py` writes
   `datetime.now(timezone.utc)` (tz-aware) into columns SQLAlchemy had
   mapped as plain `DateTime()` (Postgres `timestamp without time zone`).
   Fixed by changing every datetime column in `models.py` to
   `DateTime(timezone=True)` (`_TZ_DATETIME` helper) and amending the
   already-applied initial migration in place (`sa.DateTime()` →
   `sa.DateTime(timezone=True)` for all 6 datetime columns), then running
   the downgrade/upgrade cycle to apply it — chosen over a second follow-up
   migration since no real data existed yet and the user's decision #2
   explicitly wanted "one clean baseline."
3. **`pages.raw_html_snapshot_path` made nullable** — not explicitly called
   out in the plan text, but a necessary consequence of decision #3
   (persist every crawled page, including failed ones): `crawler.py` never
   writes a snapshot for a page that failed to load, so a NOT NULL
   constraint would break inserts for `status="failed"` rows. Flagging this
   explicitly since it's a real schema decision, not just an implementation
   detail.
4. Enum-drop gap in `downgrade()` was anticipated in the plan and fixed
   proactively before ever running the migration (not discovered via a
   failure) — listed in the plan already, executed as described.

No other deviations. Everything else matches the approved plan as written.

## 6. Ready-for-review checklist (PLAN.md Phase 1 — not applied, for your review)

- [x] Playwright crawler + axe-core detector *(already done pre-session; unchecked in PLAN.md until now)*
- [x] FastAPI endpoint returns scan_id immediately, runs crawl/detect via BackgroundTasks
- [x] GET /scan/{id} status endpoint for polling
- [x] Document BackgroundTasks limitation in design.md *(Section 4f, limitation independently verified via kill-mid-scan test, not just asserted)*
- [x] Defensive crawling: timeouts, skip+log failures, exclude authenticated pages *(unchanged, already verified pre-session)*
- [x] Deliverable: API that accepts a URL, scans async, returns structured violations
- [x] Verify: run against 2-3 real public URLs, confirm structured output *(ran against 3: usa.gov, news.ycombinator.com, example.com — all reached `done` with real persisted violation data)*

**Suggested PLAN.md session-log line** (not added — yours to add after review):
```
<!-- 2026-07-05: Phase 1 complete — built FastAPI+Postgres API layer (config.py,
     db.py, models.py, main.py), Alembic migration for all 8 schema.md tables
     (+pages.status/failure_reason, +violations.html_snippet/message per
     decisions logged in docs/schema.md), docker-compose Postgres on host port
     5433 (5432 conflicts with a pre-existing native Postgres service on this
     machine). Verified end-to-end against 3 real URLs: usa.gov (15 pages, 1
     violation), news.ycombinator.com (15 pages, 530 violations), example.com
     (1 page, 0 violations). Confirmed BackgroundTasks non-durability limitation
     live via kill-mid-scan test. Fixed a datetime timezone bug and an Alembic
     enum-cleanup gap found during verification. -->
```

## 7. What's left running

- `accessibility_agent_postgres` container: up, healthy, port 5433.
- `uvicorn main:app --port 8000`: running (PID visible via `tasklist`).
- Scan #4 intentionally left at `status=running` as evidence for item 4 above
  — safe to ignore or delete once reviewed.
