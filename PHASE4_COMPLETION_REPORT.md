# Phase 4 Completion Report — Dashboard + Verified Fixed-Page Delivery

The dashboard is real and live-verified end to end, not just built. The
biggest scope change from design.md's original architecture diagram: real
GitHub PR creation is deferred to optional Phase 6, because most scanned
sites aren't GitHub repos at all — the real Phase 4 deliverable is a
human-approved, verified, downloadable fixed copy of the page instead.
Every claim in this report was either produced by a real test run, a real
`docker compose up`, or a real headless-browser session against real data —
none are assumed.

## 1. What was built

| Component | What changed |
|---|---|
| `backend/app/agents/developer/prompt.py`, `verifier.py` | `html-has-lang`/`html-lang-valid` hardened to a targeted `setAttribute('lang', ...)` call instead of full-page outerHTML replacement, via a new shared `apply_fix_to_locator()` helper. Prerequisite for combining fixes safely — see Section 3. |
| Migration `06c057e5a1fc` + `models.py` | `Page` gains 4 nullable columns: `fixed_html_snapshot_path`, `combined_verification_status`, `combined_verification_detail`, `combined_verified_at`. Applied live to the dev DB — confirmed via `psql`, all 4 present and NULL on existing rows, 5 sites/17 scans unchanged. |
| `backend/app/page_fixer.py` (new) | `apply_verified_fixes_to_page()`: combines every approved, individually-verified fix onto the page's *already-captured* `raw_html_snapshot_path` (`page.set_content()`, never a fresh `page.goto()`), injects a `<base href>` tag, reruns the full detector once, classifies `clean`/`violations_remain`/`error`. Own-Playwright-lifecycle, no DB access — same convention as `detector.py`/`verifier.py`. Explicitly guards a null/empty `raw_html_snapshot_path` — see Section 2. |
| `main.py` | 5 new endpoints: `GET /sites`, `GET /scans`, `POST /fixes/{id}/approval`, `POST /pages/{id}/generate-fixed-page` (explicit partial-approval counts, requires ≥1 approved fix, rejects a page with no captured snapshot), `GET /pages/{id}/download-fixed`. `CORSMiddleware` scoped to a real `FRONTEND_ORIGIN` setting. `get_scan()` now also computes each fix's `latest_approval_decision` (Approval has no `relationship()` on Fix — `models.py`'s own comment invited this when actually needed). |
| `cost_report.py` | Extended with `compute_scan_performance_summary()` (throughput, pipeline time median/p95, scan success rate) and `compute_accessibility_score_trend()` (a definition introduced this phase, not discovered — see Section 3); per-agent breakdown gained `latency_ms_median`/`latency_ms_p95`/`success_rate`. Wired to new `GET /performance/summary`. |
| `frontend/` (new) | Vite + React + TypeScript. Three views (`ViolationsView`, `PerformanceView`, `ReviewApproveView`) sharing a `useScanSelector` hook; hand-mirrored TS types against `main.py`'s Pydantic models (no codegen tooling exists yet); `react-diff-viewer-continued` for diffs (see Section 5); custom `BarChart`/`TrendLineChart` built following the dataviz skill's procedure (color-last, single sequential hue, thin marks, hover tooltips). |
| `backend/Dockerfile`, `frontend/Dockerfile`, `docker-entrypoint.sh` (new) | Neither existed before this phase — only Postgres was containerized, despite CLAUDE.md's stated "frontend + backend + Postgres only" scope. Backend: Python 3.14, `playwright install --with-deps chromium` matching `ci.yml`'s own step exactly, entrypoint runs `alembic upgrade head` before serving. Frontend: `vite preview`, `VITE_API_BASE_URL` baked in at build time as the host-browser-reachable `http://localhost:8000` (deliberately not the Docker-internal service name — the frontend runs in the host's browser, which can't resolve Docker DNS). |

## 2. A review follow-up closed out: null `raw_html_snapshot_path` handling

Flagged explicitly after the drift-fix decision (Section 3's item 1) and
not addressed when this report was first written — `page_fixer.py`
depends on `Page.raw_html_snapshot_path` being populated, and that column
has been nullable since Phase 1 (only set for `status="loaded"` pages;
see `docs/schema.md`). Checked properly rather than assumed:

- **`main.py`'s `generate_fixed_page` endpoint already guarded this**
  (`if page.status != "loaded" or page.raw_html_snapshot_path is None:` →
  400) — but the guard had never been exercised by a test, and the
  original report never mentioned the case at all.
- **`page_fixer.py` itself did not**, despite its own module docstring's
  "never raises" contract. `Path(raw_html_snapshot_path).read_text(...)`
  is wrapped in `except OSError` — but `Path(None)` raises `TypeError`,
  which that clause does not catch. Confirmed directly, not just reasoned
  about:
  ```
  >>> from pathlib import Path; Path(None).read_text()
  TypeError: argument should be a str or an os.PathLike object where
  __fspath__ returns a str, not 'NoneType'
  ```
  If `page_fixer.py` were ever called directly (bypassing `main.py`'s
  guard — a future caller, a bug in the guard) with a null snapshot path,
  this would have been an unhandled 500 with a raw traceback, not the
  structured `CombinedFixResult(status="error", ...)` every other failure
  mode in this module produces.

**Fixed at both layers**, not just patched over the one reachable-today
path: `page_fixer.py` now has an explicit `if not raw_html_snapshot_path:`
check before ever constructing a `Path`, returning a clean
`status="error"` result; the parameter's type hint changed to `str |
None` to make the contract honest. Both the module-level defense and the
endpoint-level guard now have real tests:

- `test_page_fixer.py::test_none_snapshot_path_is_clean_error_not_unhandled_exception`
  — calls `apply_verified_fixes_to_page()` directly with
  `raw_html_snapshot_path=None`, asserts a clean `CombinedFixResult`, not
  an exception.
- `test_dashboard_endpoints.py::test_generate_fixed_page_null_snapshot_path_is_clean_400`
  — creates a page with `status="loaded"` and `raw_html_snapshot_path=None`
  (a combination the real crawler never produces, but nothing in the
  schema enforces that invariant, and `page_fixer.py` is a new, second
  consumer of this column beyond its original use) with a real
  verified+approved fix, calls the real endpoint, asserts a 400 with
  `"snapshot"` in the detail — not a 500.

Both pass. Full suite: **83/83** (was 81 when this report was first
written).

## 3. Four planning-time decisions, resolved before any code was written

Raised by you before implementation began, each written into `design.md`
Section 11, not silently assumed:

1. **Live-page drift.** Verification happens at scan time; human approval
   (and generation) can happen minutes, hours, or days later. Resolved by
   anchoring `page_fixer.py` to the page's already-captured
   `raw_html_snapshot_path` instead of a fresh live reload. **Proven, not
   just implemented:** `test_ignores_live_page_content_uses_snapshot_only`
   passes `page_url="http://this-domain-does-not-exist.invalid/page"` —
   combination still succeeds, because the live URL is never fetched, only
   stitched into a `<base href>` string.
2. **Partial approval allowed, explicitly.** `generate-fixed-page` proceeds
   with whatever is approved (requiring ≥1), and its response always
   reports `fixes_included_count`/`fixes_pending_count` — the frontend's
   "Generate partial fix (N/M approved)" label reads directly from this.
3. **CORS scoped, not wildcarded.** A real `FRONTEND_ORIGIN` config value,
   defaulting to `http://localhost:5173`.
4. **Accessibility score — a definition introduced, not discovered.**
   `open_violations / page_count` per scan, trended by `completed_at`. A
   direct ratio of two already-logged counts, no invented weighting.

## 4. The `html-has-lang` hardening — proven combined, not just in isolation

Before this phase, fixing `html-has-lang`/`html-lang-valid` the same way
every other rule is fixed (full outerHTML replacement) would have forced
the Developer LLM to regenerate the entire page for one attribute, and —
critically for this phase — would have silently overwritten every other
already-applied fix once multiple fixes started being combined onto one
page. `verify_fix()`'s and `page_fixer.py`'s new shared
`apply_fix_to_locator()` special-cases these two rule IDs to a targeted
attribute set instead.

Regression-proven at the exact point of risk, not just per-rule isolation:
`test_page_fixer.py::test_combines_lang_fix_with_unrelated_fix_clean`
combines an `html-has-lang` fix with an unrelated `image-alt` fix on the
same page — both land correctly (`lang="en"` and `alt="Hero image"` both
present in the final combined HTML).

## 5. A real dependency substitution, confirmed not assumed

CLAUDE.md names `react-diff-viewer`. A real `npm install` produced a hard
`ERESOLVE` failure: the package's peer dependency (`react@"^15.3.0 ||
^16.0.0"`) is incompatible with this scaffold's React 19. Switched to
`react-diff-viewer-continued` — an actively-maintained fork with the
identical component API — rather than forcing `--legacy-peer-deps` onto an
unmaintained package.

## 6. Live browser verification (Playwright, not just `tsc`/`vite build`)

`chromium-cli` wasn't available in this environment; adapted the `run`
skill's fallback pattern using the Python Playwright already in this
project's venv.

**LLM_MOCK's known limitation, worked around correctly, not ignored:**
mock Developer output's `target_selector="mock-selector"` can never
actually resolve against a real page, so a mocked `/scan` can never
produce a real `verified` fix to review. Seeded real `Violation`/`Fix` rows
directly into the dev DB instead (same pattern already used in
`test_dashboard_endpoints.py`) — one page with two genuinely-working fixes,
one page with a fix that doesn't actually fix anything.

**Golden path, driven for real:** loaded `/violations`, selected the
seeded site/scan, expanded a violation's diff (real word-level diff
rendered). Switched to Review & Approve, bulk-approved the clean page,
clicked Generate — `wait_for_selector` for the "Download fixed page"
button succeeded (a real `GET` that returns the combined HTML with the
real fix applied, not a stub).

**Edge case, driven for real:** approved the broken page's fix, clicked
Generate — confirmed via a direct locator count that **zero** download
buttons render for that page (`broken_page_download_button_count: 0`), not
just "didn't crash."

**Zero browser console errors** across both passes
(`console_errors: []`), confirmed via a `console`/`pageerror` listener, not
assumed from a clean-looking screenshot.

**Two real layout bugs found and fixed this way, not shipped unnoticed:**
- The bar chart's x-axis labels collided (`"ImpactDeveloper"` running
  together) — bars were positioned by their own width instead of equal
  category slots. Fixed the slot-centering math.
- The diff viewer overflowed its card and the page's own viewport width.
  Fixed with a scoped `overflow-x: auto` wrapper plus `min-width: 0` on
  the grid column (a CSS Grid default that otherwise lets wide content
  grow the track past its fair share).

Both re-verified live after the fix — screenshots confirm clean layout,
no clipped text, correctly-spaced labels.

Demo rows deleted afterward via a scoped, pre-confirmed-URL-pattern
cleanup script (asserted every row's URL contained `demo-ui-verify` before
deleting anything) — dev DB confirmed back to exactly 5 sites/17 scans via
`psql`, before and after.

## 7. Docker — built and actually run, not just written

Both images built successfully (`docker compose build backend frontend`),
then actually brought up (`docker compose up -d backend frontend`) — not
stopped at `docker build`. Backend logs confirmed real Alembic migration
ran before Uvicorn started; `GET /sites` through the container's port
mapping returned real dev-DB data.

**A real bug caught during this verification, not hypothetical:** an
initial `curl localhost:5173` appeared to hit the container but was
actually still being served by a **leftover local `vite dev` process** — a
genuinely separate Windows process (`node.exe`, PID 32488) invisible to
this session's bash `ps`, bound to `[::1]:5173`, which `curl
localhost`/browsers resolve to ahead of Docker's `0.0.0.0` proxy. Found via
`netstat -ano` + `tasklist`, confirmed via `docker exec ... cat
dist/index.html` that the container itself was serving the correct built
output the whole time, killed the stray process via `taskkill`, and
re-verified: a fresh Playwright pass against the real containerized pair
(frontend container → backend container — the one new variable
containerization introduces) returned **zero console errors**, confirming
CORS/`VITE_API_BASE_URL` wiring genuinely works, not just that each
container independently serves something.

Backend and frontend containers stopped after verification (not left
running unattended); Postgres left exactly as it was found.

## 8. Test results

- **83/83 pytest tests passing** (52 at Phase 3 close + 31 new: 3 lang-rule
  tests in `test_verifier.py`, 10 in `test_page_fixer.py` (9 original + the
  null-snapshot-path test from Section 2), 10 in `test_dashboard_endpoints.py`
  (9 original + the null-snapshot-path 400 test), 6 in `test_cost_report.py`,
  1 performance-summary shape smoke test, 1 `latest_approval_decision`
  regression test).
- `ruff check backend/`: clean throughout — confirmed after every step,
  not just once at the end.
- `tsc -b && vite build`: clean, both before and after the layout-bug
  fixes.
- A genuinely new test-infra bug found and fixed along the way: adding
  direct `async_session_factory` usage to `tests/api/` (interleaved with
  `test_scan_roundtrip.py`'s Playwright-heavy crawl across separate
  event loops) reproduced the exact stale-pooled-connection
  `AttributeError` Phase 2.5c already fixed for `tests/graph/` — same root
  cause, same fix (a dispose-fixture), now also applied to
  `tests/api/conftest.py` and `tests/cost_report/conftest.py`.

## 9. Known limitations carried forward (documented, not silently fixed)

- **The downloaded fixed page is a frozen snapshot**, not a live-redeployable
  artifact. Detection and fix-verification already operate on the real
  post-JS-render DOM, so JS-heavy sites are handled correctly for *those*
  two things — but a client-rendered SPA that re-hydrates on load could
  silently overwrite the injected fix the moment its own JS runs again.
  Mitigated (a `<base href>` tag for relative asset resolution), not
  solved — same documented-tradeoff treatment as BackgroundTasks'
  non-durability.
- **No frontend CI yet.** Phase 4.5 (already a placeholder in `PLAN.md`) is
  now real, scoped work instead of speculative, now that frontend code
  actually exists.
- **`pr_metrics` in `GET /performance/summary` is always `null`.** An
  honest placeholder, not a missing field — real PR metrics are Phase 6
  scope, once a real target repo exists.

## 10. Not done this phase, deliberately

- Real PyGithub PR creation — Phase 6, optional, against one real chosen
  repo, once picked.
- Frontend automated test suite + CI extension — Phase 4.5.
- Full SPA-hydration-safe standalone redeployment of the downloaded fixed
  page — documented limitation (Section 9), not solved.
- **Nothing has been committed or pushed.** All of the above is real,
  local, verified work sitting in the working tree — committing (and any
  remote CI verification) is your call, not made here.

## 11. Real final state

- 83/83 pytest tests passing locally, `ruff check backend/` clean,
  `tsc -b && vite build` clean.
- Full containerized stack (`docker compose up`) built and live-verified —
  real Alembic migration ran automatically, real API responses, real
  browser session against the containerized frontend with zero console
  errors.
- Golden path (approve → generate → download) and the `violations_remain`
  edge case (no download button) both confirmed via real browser
  automation against real seeded data, not assumed from the backend tests
  alone.
- Two real layout bugs, one real Docker networking bug, and one real
  unhandled-exception gap (null `raw_html_snapshot_path`, Section 2) found
  and fixed during verification/review, not shipped unnoticed.
- Phase 4 checkboxes closed in `PLAN.md` with a full session-log entry;
  `docs/schema.md` and `design.md` (Section 11) updated to describe the
  real behavior, including every planning-time decision's final reasoning.
