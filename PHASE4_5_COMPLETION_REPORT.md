# Phase 4.5 Completion Report — Frontend Testing + CI/CD

Fills in `PLAN.md`'s Phase 4.5 placeholder ("decided when this phase
starts, not now") now that real frontend code exists (Phase 4). Worked in
four checkpoints on a `phase-4.5` branch, each committed and pushed before
starting the next, per your explicit instruction — not batched at the end.
Every claim below is either a real local test run, a real triggered GitHub
Actions run, or a real `git diff`/`git log` check — none are assumed.

## 1. What was built

| Component | What changed |
|---|---|
| `frontend/vitest.config.ts`, `frontend/src/test/setupTests.ts` (new) | Vitest + React Testing Library, kept as a separate config file rather than merged into `vite.config.ts` — mirrors this project's existing dev/test separation pattern. `setupTests.ts` stubs `window.matchMedia` (read at module load by `ViolationDiff.tsx`), imports `@testing-library/jest-dom/vitest` (required because `globals: false`), and registers an explicit `afterEach(cleanup)` — see Section 2. |
| 11 new colocated `*.test.{ts,tsx}` files | `StatusBadge`, `TrendLineChart`, `BarChart`, `ViolationDiff` (components); `useScanSelector`, `client.ts` (hook + API layer); `ViolationsView`, `PerformanceView`, `ReviewApproveView` (pages). 60 tests total. Colocated next to source rather than a mirrored `tests/` tree (the backend's own convention) — decided explicitly, not defaulted into; see design.md Section 12. |
| `frontend/src/hooks/useScanSelector.ts` | **Production code change** — fixed a real stale-response race. See Section 3; this is not a test-infrastructure change. |
| `.github/workflows/ci.yml` | New independent `frontend` job: `actions/setup-node@v4` (22.x) → `npm ci` → `oxlint` → `tsc -b` → `vitest run` → `vite build`. No Postgres/backend services — the frontend suite mocks `api/client.ts` (or the `useScanSelector` hook directly for page tests), never a real backend, so this job has nothing to wait on. |
| `design.md` Section 12, `PLAN.md` Phase 4.5 checkboxes | Decisions and reasoning written down before/while implementing, same discipline Section 10 used for Phase 2.5. |

## 2. A real setup gap found while wiring up `setupTests.ts`

Not just a config nit — every test after the first in a file was failing
or double-counting elements. With `globals: false` (this project's
explicit-import convention, consistent with `verbatimModuleSyntax`),
React Testing Library's auto-cleanup never self-registers: it only
activates when it detects a *global* `afterEach` (jest's default, or
Vitest's `globals: true`). Confirmed directly — the first test run showed
duplicate "unknown" badges, a stale SVG causing a "multiple elements
found" error, and a bar-chart test counting 3 rects instead of 2, all
from the *previous* test's unmounted DOM still being present. Fixed with
an explicit `afterEach(cleanup)` in `setupTests.ts`, documented inline so
it isn't a silent gotcha for the next test file added.

## 3. Test infrastructure vs. the one real bug fixed along the way

Splitting this out explicitly, same treatment the Phase 4 report gave the
null-`raw_html_snapshot_path` fix — this phase was nominally "add tests,"
and one piece of it wasn't.

**The bug:** `useScanSelector.ts`'s site→scans effect and `refetchScan`
both fired a fetch with no check, on resolution, that the response still
matched the current selection. Concretely: click scan A, then scan B
before A's `getScan` call resolves — if A resolves after B, `setScan(A's
result)` would silently overwrite B's already-rendered state, with
nothing in the UI indicating this happened. Confirmed this was a genuine
gap, not a hypothetical, via a direct `grep` of `frontend/src` for
`AbortController`/`cancelled`/any staleness guard — zero matches.

**The fix**, landed before any test was written against the buggy
behavior (which would have just locked it in): the site→scans effect now
uses an effect-cleanup `cancelled` flag; `refetchScan` uses a ref-based
"latest request" token instead, since it's also invoked imperatively by
`ReviewApproveView`/`ViolationsView` outside the effect that originally
triggered it — an effect-cleanup flag alone wouldn't cover that call
path.

**Landed as its own commit** (`5fb7783`, `phase-4.5: fix
useScanSelector stale-response race`), separate from every test file, per
your explicit instruction — not folded into `phase-4.5: hook + API client
tests`.

**Regression-proven, not just fixed:** `useScanSelector.test.ts` has two
dedicated tests (`guards against a stale site->scans response`, `guards
against a stale getScan response`) that fire two overlapping requests
with the *second* resolving *first*, and assert the hook's state reflects
the current selection, not whichever settled last — plus a third test
covering the imperative `refetchScan()` call path specifically.

## 4. Test suite breakdown (60 tests)

- **Components (18):** `StatusBadge` (tone lookup + null/unknown
  fallbacks), `TrendLineChart`/`BarChart` (empty-data guards, layout math,
  hover state), `ViolationDiff` (both-null message branch). `StatTile`
  deliberately has no dedicated test — pure props-to-markup, no branches,
  implicitly covered wherever a page renders it.
- **Hook + API client (14):** `useScanSelector` (mount load, error
  propagation, site→scan cascade, the two R1 regression tests above);
  `client.ts` (`ApiError` on non-ok responses, statusText fallback on an
  empty error body, query-string construction, `downloadFixedPageUrl`
  builds the URL without touching `fetch`).
- **Pages (28):** `ViolationsView` (10 — empty states, selection wiring,
  conditional badges, expand/collapse); `PerformanceView` (6 — loading→
  error/success transitions, null-handling formatters, table rows, trend
  null-filtering); `ReviewApproveView` (11, heaviest — `approvableViolations()`
  filtering, approve/reject + disabled-when-decided, bulk-approve skip
  logic, Generate button label branching, and three dedicated tests
  locking down the download-link gate — see Section 5).

Pages that call `useScanSelector()` have that hook mocked directly rather
than driven through mocked `api/client.ts` calls — its internals are
already covered above, so page tests isolate rendering/interaction logic
without duplicating hook coverage.

## 5. The regression proof — tightened to the exact assertion, not just "CI went red"

Per your explicit instruction: when the download-link gate was inverted
to produce the red run, this report captures which specific test caught
it, not just the job's overall conclusion.

`ReviewApproveView.tsx`'s `combined_verification_status === "clean"`
check — the sole condition controlling whether the "Download fixed page"
link renders — was inverted to `!==` in a real commit pushed to
`phase-4.5`.

**Red run [29124818143](https://github.com/SiddhiKhairee/accessibility-compliance-agent/actions/runs/29124818143):**
the `frontend` job failed at the "Run Vitest suite" step. The log shows
`ReviewApproveView.test.tsx (12 tests | 3 failed)` — exactly:

```
✓ does not render a page card when it has no verified-fix violations to approve
✓ renders a page card for a page with at least one verified-fix violation
✓ clicking Approve calls createApproval with the fix id and decision, then refetches
✓ disables Approve once a violation is already approved, and Reject once already rejected
✓ 'Approve all on this page' only approves violations that aren't already decided
✓ is disabled when zero violations on the page are approved
✓ labels 'Generate fixed page (n/n approved)' when every approvable violation is approved
✓ labels 'Generate partial fix (n/m approved)' when only some approvable violations are approved
✓ calls generateFixedPage with the page id and shows the result detail
× renders the download link when the page's combined_verification_status is 'clean'
× does NOT render the download link when combined_verification_status is 'violations_remain'
× does NOT render the download link when combined_verification_status is null (never generated)
```

All 9 other tests in that file, every other test file (`StatusBadge`,
`TrendLineChart`, `BarChart`, `ViolationDiff`, `useScanSelector`,
`client.ts`, `ViolationsView`, `PerformanceView`), and the backend `test`
job all stayed green — confirming the regression was caught by the tests
built specifically for it, not incidentally by something else. Verified
locally first, before ever pushing: `npm run test -- ReviewApproveView`
produced the identical 3-failed/9-passed result.

**Reverted**, confirmed byte-clean via `git diff 47611a3 --
frontend/src/pages/ReviewApproveView.tsx` (empty output — the file
matches the pre-regression commit exactly, not just "looks reverted").

**Green run [29124965399](https://github.com/SiddhiKhairee/accessibility-compliance-agent/actions/runs/29124965399):**
both `frontend` and `test` jobs passing.

## 6. Branch hygiene — a real mistake, caught and corrected mid-session

The R1 fix (Section 3) was committed directly to local `main` before a
`phase-4.5` branch existed — an oversight, not intentional (a branch
should have been created first). Caught before any push:

- Confirmed via `git fetch origin main` + `git log origin/main..main` /
  `git log main..origin/main` (both empty except for the one local
  commit) that `origin/main` was completely untouched.
- Created `phase-4.5` at that commit; moved local `main`'s pointer back
  to `origin/main` — **confirmed with you explicitly before running**,
  since this session's tooling treats branch-pointer moves as
  destructive regardless of whether they touch shared history.
- Final commit order on `phase-4.5` is R1-fix-first rather than
  interleaved with the Checkpoint 1 tooling commit (your originally
  requested order) — a deliberate, explicitly-confirmed tradeoff to avoid
  a history-rewriting `git reset` for what would have been a purely
  cosmetic reordering. Still four separate, non-squashed commits for
  Checkpoints 1–3, plus two more for the CI extension and the
  regression-proof push/revert pair.

## 7. Test results

- **60/60 frontend tests passing** (Vitest), confirmed both locally and
  in the real CI run.
- `npx tsc -b`: clean.
- `npx oxlint`: clean (pre-existing tooling from Phase 4, not newly
  introduced — confirmed via `package.json`'s existing `lint` script and
  `.oxlintrc.json` before assuming otherwise).
- `npm run build` (`vite build`): clean.
- Backend suite unaffected: this phase touched only `frontend/` and
  `.github/workflows/ci.yml`.

## 8. Not done this phase, deliberately

- **Branch protection not touched.** Adding the new `frontend` check to
  `main`'s `required_status_checks` needs your explicit go-ahead at that
  specific step (design.md Section 12, Decision 6) — not bundled into
  "the CI job is green now."
- **No PR into `main` opened.** Per your instruction, only once this
  phase is fully done and you've reviewed it.
- **Browser-driven E2E (Playwright) in CI** — out of scope for 4.5 from
  the start (see design.md Section 12); Phase 4's manual live-Playwright
  verification wasn't automated into CI, which would need standing up
  backend+Postgres+frontend containers inside Actions, a materially
  different piece of work.

## 9. Real final state

- 60/60 frontend tests passing, `tsc -b` clean, `oxlint` clean, `vite
  build` clean — all confirmed locally at every checkpoint, not just once
  at the end.
- Real triggered CI runs, not YAML review: a clean green run
  (`29124661299`) proving the new job works, a real red run
  (`29124818143`) proving it catches a real regression at the exact
  assertion built for it, and a real green run after reverting
  (`29124965399`).
- One real production bug (R1, Section 3) found and fixed, landed as its
  own clearly-labeled commit, regression-tested.
- One real setup gap (Section 2, RTL auto-cleanup) found and fixed before
  it could mask failures in later checkpoints.
- One real branch-hygiene mistake (Section 6) caught mid-session,
  corrected with your explicit confirmation before any destructive git
  operation.
- One unrelated drive-by fix: `design.md` Section 11 ended with a stale
  "Full narrative in `PHASE2_5_COMPLETION_REPORT.md`" copy-paste leftover
  (should reference `PHASE4_COMPLETION_REPORT.md`) — corrected while
  adding Section 12 immediately after it.
- `phase-4.5` branch pushed, tracking `origin/phase-4.5`. `main` confirmed
  untouched throughout.
