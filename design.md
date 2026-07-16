# design.md — Accessibility Compliance Agent (v0 draft)

## 1. One-line pitch
Agentic system that crawls public websites, detects WCAG violations, runs a
4-node LangGraph workflow to reason about and fix them, verifies fixes
locally, and requires human approval before opening a real GitHub PR.

## 2. Locked v1 rule set

All 9 rules are fully automated via axe-core — no manual-judgment rules.

| # | WCAG Success Criterion | axe-core rule IDs |
|---|---|---|
| 1 | Non-text Content (1.1.1) | `image-alt`, `input-image-alt` |
| 2 | Contrast Minimum (1.4.3) | `color-contrast` |
| 3 | Name/Role/Value — forms (4.1.2) | `label`, `button-name`, `aria-input-field-name` |
| 4 | Keyboard (2.1.1) | `tabindex` (positive-tabindex anti-pattern only — see Section 3) |
| 5 | Language of Page (3.1.1) | `html-has-lang`, `html-lang-valid` |
| 6 | Bypass Blocks (2.4.1) | `bypass`, `skip-link` |
| 7 | Duplicate ARIA/label IDs (4.1.2) | `duplicate-id-aria` |
| 8 | Info and Relationships — structural only (1.3.1) | `list`, `listitem`, `definition-list` |
| 9 | Link Purpose — presence only, not quality (2.4.4) | `link-name` |

Rules #3 and #7 both cite 4.1.2 but are kept separate: #3 catches elements
with *no* accessible name at all (missing label/text), while #7 catches
elements that technically have a name/label reference, but where a
duplicate `id` makes that reference ambiguous — a structurally different
failure requiring a different fix (rename/dedupe an ID vs. add a label).

## 3. Explicit exclusions (v1 scope boundary)

**AAA-level rules are out of scope.** WCAG AAA criteria (e.g. sign
language for video, enhanced contrast 7:1, no-timing requirements) are not
required for legal/practical compliance in the vast majority of
jurisdictions and organizations — AA is the standard baseline (ADA, EN
301 549, Section 508 all reference AA). Including AAA would inflate the
violation count with fixes most site owners wouldn't prioritize, and several
AAA criteria are inherently subjective (e.g. "Reading Level" 3.1.5).
Defensible position: v1 targets what's actually enforceable and actionable.

**Subjective/semantic rules are out of scope.** Rules like alt-text
*quality* (is this alt text actually descriptive of the image?), link-text
*quality* (does this link text meaningfully describe its destination
beyond just existing?), or heading-structure *appropriateness* require
judging meaning, not structure. axe-core can detect *presence/absence* and
structural correctness (an `<img>` has an `alt` attribute; a `<link>` has
text content) reliably and automatically — it cannot reliably judge whether
that content is *good*. Automating a semantic judgment call would mean the
Reviewer/Developer agents are guessing at correctness with no ground truth
to verify against, which conflicts with the project's core promise: every
fix is deterministically verifiable (re-run the detector, confirm the
violation is gone). Rule #9 (Link Purpose) is deliberately scoped to
"presence only" for this exact reason — the project checks that a link
has an accessible name, not that the name is well-written.

**Audio/video rules are out of scope.** Captions (1.2.2), audio
descriptions (1.2.5), and other time-based media criteria require either
human transcription/review or specialized ML models outside this
project's stack (Playwright + axe-core + a local LLM via Ollama). axe-core
itself does not evaluate media accessibility beyond flagging missing
`<track>` elements, and there's no automated way to verify a caption's
*accuracy* against the fix-and-reverify loop this project is built around.
Sites without audio/video content (the common case for the target site
sample) would also make this a low-yield category for v1 evaluation data.

**WCAG 4.1.1 Parsing is fully out of scope, in any form.** WCAG 2.2
removed 4.1.1 entirely, and axe-core deprecated and disabled the plain
`duplicate-id` rule that used to map to it. Rule #7 in the v1 set
(`duplicate-id-aria`) is retained solely because it's now classified
under 4.1.2 (Name, Role, Value) — it catches duplicate IDs that break
ARIA/label references, not generic duplicate-ID parsing. No axe-core
rule tied to 4.1.1 is included in v1.

**Keyboard traps (2.1.1) are not statically detectable, and v1 does not
detect them.** A true keyboard trap (focus enters a component and can't
tab back out) can only be observed by actually simulating tab-key
navigation at runtime — axe-core has no rule for this because it never
executes real keyboard input, only static/DOM analysis. `detector.py`'s
`tabindex` rule only catches the *positive-tabindex* anti-pattern
(disrupts natural tab order), which is a real but much narrower slice of
2.1.1 than "keyboard traps" implies. Flagging this explicitly so Phase 5's
EVALUATION.md never reports 2.1.1 coverage/precision numbers that read as
if trap detection happened — per CLAUDE.md, no invented or overstated
metrics.

**`bypass`, `duplicate-id-aria`, and `color-contrast` (2.4.1 / 4.1.2 / 1.4.3)
can each genuinely fail without ever surfacing as a `Violation` row under
the original detector.py, even though all three are locked v1 rules.** Two
different discovery paths, two different underlying mechanisms:

- `bypass` / `duplicate-id-aria`: discovered during Phase 2.5b
  regression-test fixture verification (not previously documented).
  axe-core marks both rules `reviewOnFail: true` in its own rule metadata,
  meaning a genuine failure of either *always* lands in axe's `incomplete`
  result array, not `violations`. Confirmed directly: a fixture page with
  no skip-link/heading/landmark, and a fixture with a duplicate id
  referenced via `aria-labelledby`, were both run through a raw axe call
  and genuinely failed, landing in `incomplete` each time (see
  `backend/tests/detector/test_detector.py`'s
  `test_bypass_incomplete_gap_now_surfaces_as_needs_review` and
  `test_duplicate_id_aria_incomplete_gap_now_surfaces_as_needs_review`).
- `color-contrast`: discovered later, during the real Pass 1a crawl against
  target.com (Phase 2.6 Part 1) — not via metadata. `color-contrast` is not
  tagged `reviewOnFail` at all, so the metadata-only audit below missed it
  entirely. A real page can still push a genuine `color-contrast` failure
  into `incomplete` at runtime when axe can't resolve a single background
  color for the text (an ambiguous/overlapping background, or a background
  image rather than a flat color) — confirmed reproducible on two
  independent, differently-constructed cases: target.com itself, and
  `color_contrast_ambiguous.html` (a background-image case built
  specifically to reproduce it — see
  `test_color_contrast_incomplete_gap_now_surfaces_as_needs_review`).
  `color-contrast`'s *simple* case (`color_contrast.html`, flat
  low-contrast text) is unaffected and still lands in `violations` — the
  gap is page-dependent, not purely rule-dependent.

In every case, `detector.py`'s `detect_violations()` only reads
`results.response["violations"]`, so no fixture — however constructed —
could make the affected rule appear in its output before this was fixed.

**Metadata-only audit (Phase 2.6, first pass).** A full audit of axe's own
metadata (live: loaded the real bundled `axe.min.js` in headless Chromium
and queried `axe._audit.rules` directly for `reviewOnFail` across all 16
rule IDs spanning the 9 locked rules) confirmed `bypass` and
`duplicate-id-aria` are the *only* 2 rules tagged `reviewOnFail: true`. This
was read at the time as "nothing else was silently missed," and
`REVIEW_ON_FAIL_RULE_IDS` was scoped to just those 2 rule IDs. **That
conclusion was incomplete.** Metadata predicts *"this rule always needs
human judgment on a genuine fail"* — it does not predict *"this rule's
automated check can become ambiguous on some pages."* Those are two
different mechanisms axe can produce `incomplete` results through, and only
the first is visible in `axe._audit.rules`. The `color-contrast` gap above
is exactly the second kind; metadata-only auditing could not have found it.

**Full runtime audit + fix (Phase 2.6 Part 1 + Part 2).** Following the
`color-contrast` discovery on target.com, all 16 locked rule IDs were
re-audited empirically instead of via metadata: each rule's genuine-failure
fixture (reused where one existed, built new for `skip-link`, which had
none) was run through a raw axe call, with the bucket (`violations` vs
`incomplete`) read directly off `results.response`. Result: `color-contrast`
was the only rule beyond the original 2 that needed the same treatment; the
other 13 rule IDs landed cleanly in `violations` on their fixture.
`REVIEW_ON_FAIL_RULE_IDS` is now `["bypass", "duplicate-id-aria",
"color-contrast"]` — `detect_violations()`'s `incomplete`-array handling is
unchanged in mechanism, still tagging `detection_confidence="needs_review"`
(vs `"confirmed"` for normal `violations` entries), just scoped to 3 rule
IDs derived from two different kinds of evidence (metadata for 2, runtime
audit for 1) instead of metadata alone. A pre-flight check (real raw axe
call against all 3 fixtures) confirmed `impact` — which becomes `severity`
— is present and non-null on each rule's `incomplete` nodes, so no
fallback-severity special-casing was needed. No new migration was needed:
the existing nullable `violations.detection_confidence` column (Alembic
revision `92f78d8d9d6b`) already supports arbitrary string values —
`color-contrast`'s `needs_review` rows reuse it as-is (see docs/schema.md
for the NULL-vs-"confirmed" backfill note).

**Audit honesty caveat, not just for color-contrast.** The other 13 rule
IDs were each confirmed safe against exactly ONE genuine-failure fixture
apiece (see the Phase 2.6 Part 1 audit table, PLAN.md session log). That
reduces risk — it does not prove no other page construction could ever push
one of those 13 into `incomplete` too, the same way `color-contrast`'s own
simple fixture stayed safely in `violations` right up until a real, more
complex page (target.com) showed otherwise. If evaluation data ever looks
anomalously sparse for a specific locked rule later (e.g. a rule that
should appear often across the 30-site eval corpus showing suspiciously few
hits), that should be treated as a signal worth re-auditing that specific
rule, not dismissed as the site sample simply not tripping it.

**Known limitation, intentionally scoped this way:** this phase only makes
`needs_review` violations *surface and persist* — it does not change how
the Reviewer / Impact / Developer nodes treat them. A `needs_review`
violation flows through Reviewer/Impact/Developer identically to a
`confirmed` one today. Actually using `detection_confidence` to add extra
scrutiny (e.g. in the Reviewer Agent's prompt or confidence logic) is
deferred to a later phase, not decided here — flagged explicitly so this
doesn't quietly become an undocumented gap replacing the ones just closed.

**Partially addressed in Phase 3:** the Verifier's before/after diff
(`verifier.py`'s `verify_fix()`) deliberately ignores `detection_confidence`
entirely — its baseline/after-set pairs are plain `(wcag_rule,
element_selector)` tuples, so a `needs_review` violation participates in
the "original gone, no new violation" check exactly like a `confirmed`
one (confirmed via a real fix against `duplicate_id_aria.html`'s
`needs_review` violation — see PLAN.md's Phase 3 session log). This was a
deliberate choice, not an oversight: axe itself already isn't fully
confident about these rules, so demanding *more* certainty at
verification time than detection time would be inconsistent — the
Verifier's job is to confirm the violation is gone, not to re-litigate
axe's own confidence in having found it originally.

**Common thread:** every rule in the v1 set has (a) a deterministic
axe-core check, and (b) a deterministic re-verification path — the
Verifier Agent can always confirm "violation gone, no new violation
introduced" without human judgment. Any rule that can't clear that bar is
deferred past v1.

## 4. Critical-path criteria

Critical path = any page representing a required step in a core user task
(transacting, authenticating, searching, or primary navigation), rather
than supplementary content. V1 concrete instances:
- Checkout / payment flows
- Login / auth flows
- Primary forms (signup, contact, etc.)
- Search (`/search` or equivalent)
- Primary navigation / header

The Impact Agent applies URL-pattern heuristics first against this list
(e.g. `/checkout`, `/cart`, `/login`, `/payment`, `/search`) and only
falls back to the LLM for ambiguous cases.

## 4b. Crawler design

**Same-domain only.** The crawler never follows a link off the starting
domain. Without this, a single scan could wander into ad networks, payment
processor domains, or embedded third-party widgets — none of which are the
site being audited.

**Breadth-first, hard-capped.** Default `max_pages=15`, `max_depth=2`
(homepage → direct links → one level deeper). A site is never crawled
exhaustively — the goal is a representative sample with bounded, predictable
runtime, whether the target is a 5-page nonprofit site or a large e-commerce
catalog with tens of thousands of pages. `max_pages` bounds total page
*attempts* (loaded + failed), not just successful loads, so a scan against a
site with a high failure rate still terminates in bounded time rather than
retrying its way through the whole crawl budget.

**Critical-path URL prioritization.** Links matching the critical-path
patterns from Section 4 (`checkout`, `cart`, `login`, `signin`, `signup`,
`register`, `contact`, `search`) are crawled before generic links, at any
depth. This means even a small, capped crawl reliably reaches the pages the
Impact Agent cares about most, instead of depending on link order in the
raw HTML. Verified against usa.gov: `/contact-center` and `/contact-irs`
were pulled forward into the crawl ahead of generic pages discovered at the
same depth.

**Authenticated pages are excluded by omission, not detection.** The
crawler never logs in or holds a session. Pages that require auth and
redirect to a login page are handled by the same skip+log path as any
other failed/blocked page — no separate "is this page authenticated" check
was needed.

**Failure handling matches the CLAUDE.md hard rule:** each page load has
its own timeout (10000ms, `networkidle` — see Section 4c) and a failed page
is logged with a `failure_reason` and skipped, never crashing the rest of
the crawl. Verified directly: python.org's homepage times out on
`networkidle` (likely persistent background connections) and the crawler
reported `0/1 pages loaded successfully` cleanly instead of raising.

**Bot-blocking detection (Phase 4.6).** Playwright's `page.goto()` only
raises on network-level failures — it does not raise on 4xx/5xx HTTP
responses, so a naive implementation would silently record a bot-blocked
page as `status="loaded"` and scan a 403/CAPTCHA page for accessibility
violations. `crawler.py` now checks `response.status` explicitly after
every navigation and treats 403/429/503 as `status="failed",
failure_reason="blocked (status N)"` (404/500/etc. are left as `"loaded"`
— those are real app errors, not bot-blocking). It also does a best-effort
substring sniff (`CHALLENGE_MARKERS`) against the rendered HTML for common
CAPTCHA/Cloudflare-interstitial pages that return a 200 status, classifying
a match the same way (`failure_reason="blocked (challenge page
detected)"`). Both paths skip snapshot storage, detection, and link
extraction — same as any other failed page. This is a heuristic, not a
guarantee: it will miss anti-bot pages using unrecognized markers, and a
`User-Agent` change was considered but deferred (no fingerprint-based
blocking evidence found during verification — see
PHASE4_6_COMPLETION_REPORT.md).

**Explicitly deferred, not built into v1:** sitemap.xml parsing (not
universal, and inconsistent in size/quality across sites), infinite-scroll
handling (rarely surfaces genuinely new pages, just more of the same one),
and subdomain crawling (reopens the "how far do we wander" problem
same-domain-only was meant to close).

**Known recall limitation, accepted for v1:** a hard page cap plus
pattern-based prioritization can still miss an important page that doesn't
match common naming conventions (e.g. checkout living at `/proceed-order`).
This is a defensible, honestly-documented limitation for EVALUATION.md
(Phase 5), not a bug to silently work around.

**Raw HTML storage convention.** Each loaded page's full rendered HTML is
saved to `/data/raw_html/<sha256(url)[:16]>.html` (gitignored — local
artifacts, not committed). This path is what `pages.raw_html_snapshot_path`
points to once the DB layer exists.

## 4c. Detector design — rule filtering

The standalone detector proof (see Phase 1 session log) surfaced that
axe-core's default options return violations for its *entire* rule catalog
(~90+ rules) — not just the 9 rules locked in Section 2. Tested against 7
real sites, several (amazon.com, usa.gov) returned violations that were
**100% outside the locked v1 scope** (landmark/heading/region best-practice
rules, not tied to a WCAG success criterion at all).

Fix: pass `runOnly: {type: "rule", values: LOCKED_RULE_IDS}` in axe's
`options` argument, so axe-core only *evaluates* the 9 locked rules in the
first place, rather than evaluating everything and filtering after the
fact. Re-verified on the same 7 sites post-fix — e.g. Hacker News dropped
from 7 reported violations to 4 (the 3 removed were all out-of-scope
landmark/heading rules); Amazon and usa.gov dropped to 0 (all of their
prior violations were out of scope). Confirms the filter is restricting
axe's evaluation, not just relabeling results.

## 4d. Detector design — real module interface and output shape

**Takes an already-loaded `Page`, not a URL.** `detect_violations(page)`
assumes the crawler has already navigated to and rendered the page. This
is the crawler/detector split from design.md's architecture: the crawler
owns page discovery, loading, and defensive handling; the detector's only
job is running axe-core against a page that's already in front of it. The
detector never calls `page.goto()` itself in the real module (the
standalone test script still does, since it has no crawler to hand it a
page — that's the one meaningful difference between the two).

**Returns structured data, not a report string.** `Axe.generate_report()`
(used in the standalone proof) produces human-readable text — fine for
eyeballing during testing, useless for persisting to a database. The real
module returns a list of `Violation` dataclasses (`wcag_rule`,
`element_selector`, `severity`, `html_snippet`, `message`), read directly
from axe's raw `results.response["violations"]` dict. Field mapping is
direct: axe's `impact` (`minor`/`moderate`/`serious`/`critical`) becomes
`severity`; a node's `target` (CSS selector list) becomes
`element_selector`. Both map 1:1 onto `violations` table columns in
docs/schema.md.

**One `Violation` per (rule, element) pair — not per rule.** axe-core
groups all elements failing a rule under one entry for that rule. The
`violations` table is one row per offending element, so `detect_violations`
flattens `rule → nodes` into one `Violation` per node. This produces a
real granularity jump from the earlier standalone proof: on Hacker News,
the standalone script reported "4 violations" (4 distinct rules); the real
module reports 246 (242 low-contrast elements + 2 missing-alt images + 1
unnamed link + 1 unlabeled field) — same 4 underlying rules, correctly
broken out per affected element. Verified this wasn't a bug by cross-
checking the per-rule counts summed back to 246 and matched the same 4
rule IDs found in the earlier proof.

**No `confidence` field, deliberately.** `docs/schema.md`'s `violations`
table has a `confidence` column, but axe-core has no equivalent signal to
offer — it's a deterministic pass/fail check, not a probabilistic one.
Rather than invent a placeholder value, the `Violation` dataclass omits
the field entirely. `confidence` gets populated later by the Reviewer
Agent (Phase 2), which is the actual source of that judgment.

## 4e. Wiring crawler + detector together

`crawl_site()` now calls `detect_violations(page)` on each page immediately
after it loads, while the `Page` object is still open — before the
crawler's own `finally: await page.close()` runs. This is the only point
where the two modules can connect: the detector has no way to load a page
itself, and once the crawler closes it there's nothing left to analyze.

**Detection failures are classified separately from load failures.** A
page can load correctly but still fail during axe-core analysis (e.g. an
unusual DOM breaking script injection). Conflating that with a
`page.goto()` failure would misreport a perfectly loadable page as
"failed." `CrawledPage` carries both `failure_reason` (crawler-level: the
page never loaded) and `detection_error` (detector-level: the page loaded
fine, but analysis on it failed) as separate fields, populated by two
separate try/except blocks — the outer one around `page.goto()`, an inner
one around `detect_violations()`. A page with a `detection_error` still
counts as `status="loaded"`.

**Detection runs under its own timeout, independent of the page-load
timeout.** `detect_violations()` is wrapped in
`asyncio.wait_for(..., timeout=DETECTION_TIMEOUT_S)` (10s). Without this,
one page with a pathologically slow or hanging axe-core run could stall
the entire crawl — the same "one bad page shouldn't take down the whole
scan" principle CLAUDE.md already requires for page loads applies equally
to detection.

**`violations` defaults via `field(default_factory=list)`, not a bare
`[]`.** A bare mutable default (`violations: list[Violation] = []`) is a
dataclass error — dataclasses raise `ValueError` on mutable defaults, and
even where it's silently allowed by other means, it would share one list
instance across every `CrawledPage`, corrupting each page's violation
count with every other page's data.

**Verified against two real sites post-wiring:** `usa.gov` — 15/15 pages
loaded, 0 violations, 0 detection errors, confirming the pipeline runs
cleanly end to end on a clean site. `news.ycombinator.com` — the depth-0
homepage independently reported 246 violations, matching the earlier
detector-only proof exactly; other crawled pages (`/lists`: 23,
`/item?id=...`: 143) each carried their own distinct counts, confirming
violations are being generated fresh per page, not duplicated or
carried over from a shared default.

## 4f. Known limitation — FastAPI BackgroundTasks is in-process, not durable

`POST /scan` schedules the crawl+detect+persist work via
`BackgroundTasks.add_task`, which runs in the same Python process and event
loop as the API server. Two concrete consequences, accepted for v1 rather
than fixed:

**No durability across restarts.** If the server process restarts or
crashes while a scan is `running`, nothing resumes it — the scan's row stays
at `status="running"` in Postgres forever, with no automatic detection that
it's actually dead. Verified directly during Phase 1 build-out: a scan was
killed mid-crawl (server process terminated while `status="running"`), the
server was restarted, and the scan's row was confirmed still stuck at
`status="running"` with no process anywhere aware of it — this is the
expected, accepted behavior, not a bug. (A startup sweep that marks stale
`running` scans as `failed` would be a cheap partial mitigation, but isn't
built in v1 either — noted here rather than silently patched in.)

**No shared browser pool across concurrent scans.** `crawl_site()` launches
its own Chromium instance per call (`async_playwright()` +
`chromium.launch()`); two scans POSTed close together run as two independent
browser processes competing for the same machine's resources, not a managed
pool.

**Natural next step, not built now:** swap `BackgroundTasks` for a
Redis-backed queue (e.g. Celery, RQ, or Arq) with a separate worker process.
That would give durability across restarts, real retry semantics, and
queue-depth visibility — none of which BackgroundTasks can offer. This is an
intentional v1 scope limitation per CLAUDE.md, not an oversight.

## 5. Architecture diagram

```
                    ┌─────────────────┐
   Target URL  ───► │  Playwright      │   crawls pages, defensive
                    │  Crawler         │   per-page timeouts,
                    └────────┬─────────┘   skip+log on failure
                             │
                             ▼
                    ┌──────────────────┐
                    │  axe-core         │  detects violations against
                    │  Detector         │  the locked 9-rule v1 set
                    └────────┬──────────┘
                             │  structured violations
                             ▼
        ┌───────────────────────────────────────────────┐
        │           LangGraph 4-Node Workflow             │
        │                                                 │
        │   ┌───────────┐   ┌───────────┐                 │
        │   │ Reviewer  │──►│  Impact   │                 │
        │   │ Agent     │   │  Agent    │                 │
        │   │(confirms  │   │(URL       │                 │
        │   │ WCAG rule,│   │ heuristics│                 │
        │   │confidence)│   │ + LLM     │                 │
        │   └───────────┘   │ fallback) │                 │
        │                   └─────┬─────┘                 │
        │                         ▼                        │
        │                   ┌───────────┐                 │
        │                   │ Developer │                 │
        │                   │ Agent     │                 │
        │                   │(fix @     │                 │
        │                   │ selector) │                 │
        │                   └─────┬─────┘                 │
        │                         ▼                        │
        │                   ┌───────────┐                 │
        │                   │ Verifier  │                 │
        │                   │ Agent     │                 │
        │                   │(re-run    │                 │
        │                   │ FULL      │                 │
        │                   │ detector) │                 │
        │                   └─────┬─────┘                 │
        └─────────────────────────┼──────────────────────┘
                                  │  verified / manual_review
                                  ▼
                    ┌──────────────────────┐
                    │  FastAPI + Postgres    │  scan status, violations,
                    │  (BackgroundTasks)     │  fixes, agent logs
                    └───────────┬────────────┘
                                 │
                                 ▼
                    ┌──────────────────────┐
                    │  React Dashboard       │  Violations / System
                    │  (react-diff-viewer)   │  Performance / Review &
                    │                        │  Approve tabs
                    └───────────┬────────────┘
                                 │  human clicks "Approve & Open PR"
                                 ▼
                    ┌──────────────────────┐
                    │  PyGithub → real PR    │
                    └──────────────────────┘
```

Every LLM/agent call in the 4-node workflow logs `latency_ms`,
`tokens_used`, `model_used`, `cache_hit` (Reviewer also logs
`confidence_score`) for the System Performance dashboard.

## 6. DB schema summary

Full column-level definition lives in `docs/schema.md` — this is a
pointer, not a restatement. Schema changes go through a migration, never
hand-edited in prod.

| Table | Purpose | Key fields |
|---|---|---|
| `sites` | A crawled site | `url`, `last_scanned_at` |
| `scans` | One crawl run against a site | `site_id`, `status` |
| `pages` | A page visited within a scan | `scan_id`, `url`, `raw_html_snapshot_path` |
| `violations` | A detected WCAG violation on a page | `page_id`, `wcag_rule`, `element_selector`, `status` |
| `impact_assessments` | Impact Agent output for a violation | `violation_id`, `is_critical_path`, `business_risk_score` |
| `fixes` | Developer Agent proposed fix + verification outcome | `violation_id`, `proposed_code_diff`, `verification_status`, `failure_reason` |
| `approvals` | Human approval decision + resulting PR | `fix_id`, `decision`, `pr_url`, `pr_status` |
| `llm_call_logs` | Per-agent-call instrumentation for the System Performance dashboard | `agent_name`, `latency_ms`, `tokens_used`, `model_used`, `cache_hit`, `confidence_score` |

No orgs/users/multi-tenancy tables — no real concurrent users to justify
the complexity.

## 7. Phase 2 — LLM stack change: local Ollama → Groq-hosted `qwen/qwen3-32b`

CLAUDE.md originally locked "LLM: local via Ollama (zero cost)." This
changed during Phase 2 planning, tested rather than guessed, and is
recorded here per CLAUDE.md's own rule that tech-stack substitutions must
be flagged, not silently swapped in.

**Why local Ollama was dropped.** This dev machine has only ~2.2GB RAM
free of 16GB total (Docker's WSL VM, IDE, browsers already consuming the
rest, confirmed via `Get-CimInstance`). A local 7B-class model's ~5.5-6.5GB
resident footprint risked swap-thrashing alongside Docker/Postgres/
Playwright during an actual scan, not just slow inference.

**Why Groq, and why `qwen/qwen3-32b` specifically.** Evaluated Cerebras's
free tier first (checked directly against `inference-docs.cerebras.ai`,
not aggregator blogs) — no Qwen model on its catalog, and a 5 requests/
minute cap too slow for this pipeline's sequential per-violation calls.
Ran a real side-by-side benchmark (one live Reviewer-agent call, same real
usa.gov violation) between `qwen/qwen3-32b` and `openai/gpt-oss-120b` on
Groq's free tier: identical quality (0.95 confidence, correct verdict,
both). Chose qwen3-32b because Groq's 30 RPM cap on gpt-oss-120b is
*tighter* than gpt-oss's own real speed (856ms/call), wasting its speed
advantage, while qwen3-32b's 60 RPM cap is *looser* than its own real
speed (1456ms/call) — its real bottleneck is its own latency, netting more
effective throughput despite being individually slower per call. qwen3-32b
also has 2.5x gpt-oss's daily token budget.

**Real, not hypothetical, cost:** genuinely free (no card, verified
against Groq's own docs), but a third-party API — page HTML/violation
content leaves the machine. Acceptable since the project only ever
touches public site content.

**Correction discovered during live testing, not planning:** the RPM-based
throughput analysis above missed the actual binding constraint. Groq's
real limit for this account is **6,000 tokens/minute**, not requests/
minute — confirmed via the `x-ratelimit-limit-tokens` response header. At
~650 tokens per real call, that's roughly 9 calls/minute sustainable, far
tighter than the ~41 calls/minute the RPM-only analysis predicted. Running
a real scan against 43 real violations (W3C's WAI "bad" accessibility demo
page — a real public page built for testing a11y tooling) confirmed this
directly: after the first few calls, every subsequent call hit a real 429
until the per-minute token window rolled over. Noted here as a real,
measured limitation for Phase 3/5 capacity planning, not a projection.

**Non-strict JSON mode, not strict structured output.** Groq's strict,
schema-guaranteed structured-output mode (`response_format: json_schema,
strict: true`) is only supported on gpt-oss-20b/120b, not qwen3-32b
(confirmed against Groq's own structured-outputs docs). `reasoning_format:
"hidden"` (which suppresses qwen3's `<think>...</think>` trace from the
visible response) and strict structured output are unrelated features —
hiding the reasoning trace does not grant a format guarantee. Phase 2 uses
non-strict `{"type": "json_object"}` plus real Pydantic validation; a
validation failure is a real, fully-handled failure mode (see below), not
a bug.

**Correction, found during Phase 1+2 coordination testing (not at initial
Phase 2 verification):** the claim above originally said non-strict mode
"guarantees valid JSON syntax, not schema conformance" — implying we'd
always get *something* parseable back to validate against our schema.
That's not quite what happens. Groq validates the model's raw generation
server-side, and if that check fails, it doesn't hand us the broken text
— it rejects the *entire request* with an HTTP 400
(`code: "json_validate_failed"`) and an empty `failed_generation` field.
So the real behavior is "valid JSON, or total rejection with zero
recoverable content" — not "valid JSON, or a malformed string we can at
least inspect." This is a strictly worse debugging situation than a
Pydantic `validation_error` (where `raw_content` is captured in full):
here, `error` only ever contains the generic 400 exception text, since
`raw_content` never gets populated. Reproduced directly on a real
`listitem` violation from usa.gov (retried the identical call, failed
identically) — not a transient blip. Already safe: caught as a non-429
`httpx.HTTPStatusError`, classified `error_type="http_error"`, that
violation cleanly aborted with zero partial state, same as any other
failure. Only 2 data points exist so far — not enough to tell whether
this is content-dependent or just sampling variance at temperature=0.2,
so no prompt tuning has been attempted. If `error_type='http_error'`
shows up at a meaningful rate during Phase 5's per-rule failure-rate
tracking (Section 9), that's the real trigger to investigate further.

## 8. Phase 2 — reasoning layer architecture

**Exactly 4 LangGraph nodes** (`backend/app/graph.py`), linear edges,
Reviewer → Impact → Developer → Verifier → END. Verifier was a structural
stub in Phase 2 (returned `status="pending_verification"`, no LLM call, no
Playwright re-check).

**Phase 3: Verifier is real, no graph restructuring needed.**
`verifier_node` calls a new flat module, `backend/app/verifier.py`'s
`verify_fix()` (same own-Playwright-lifecycle convention as
`detector.py`/`crawler.py`, no DB access): loads the live page fresh,
validates `proposed_code_diff` structurally (stdlib `html.parser`
tag-balance check — catches gross/truncated breakage, not a full HTML
validator, since none is in `requirements.txt`), replaces the target
element's outerHTML via `Locator.evaluate()`, reruns the **full**
`detect_violations()`, and diffs the whole after-set against the page's
pre-fix baseline (threaded into `ReasoningState` by `run_scan`, never
queried by the node itself — nodes still never touch the DB). Verdicts:
`verified` (original gone, no new violation), `rejected` (fix and
re-detection both ran cleanly, but the violation persists or a new one
appeared — a confident automated "no"), or `manual_review` (a technical
failure — timeout, invalid HTML, selector didn't resolve, apply threw —
persisted through one mechanical retry, i.e. failure_reason is set).
Retry is mechanical only: same `proposed_code_diff`, freshly reloaded
page, no new Developer LLM call — so Verifier itself never appears in
`llm_call_logs`. `fixes.verified_at` is stamped on any terminal verdict,
not only `verified`, matching `scans.completed_at`'s stamp-on-success-or-
failure precedent. Verified live against real Groq output (not just
mocked tests): a real Developer-proposed fix for a `missing_alt.html`-
style violation was applied via real Playwright DOM mutation and
confirmed `verified` end-to-end.

**Nodes are pure functions over a shared per-violation state dict — none
of them touch the database.** `main.py`'s `run_scan` invokes the compiled
graph once per open violation (sequentially — matches Groq's real rate
limits above) and only commits `violations.confidence`/
`impact_assessments`/`fixes` together, in one transaction, after the full
graph succeeds. A failure at any node (Groq timeout, rate limit, malformed
JSON, schema-validation failure) propagates straight out of
`graph.ainvoke()` before any DB write happens for that violation — so a
partially-successful run (e.g. Reviewer and Impact succeed, Developer
hits a 429) leaves that violation with **zero** rows in
`impact_assessments`/`fixes`, identical to "not yet processed," never a
half-written row. Verified live: a real 429 on the Developer node during
testing left `violations.confidence` null and 0 rows in both
`impact_assessments` and `fixes` for that violation, confirmed via direct
`psql` query.

**Impact Agent's URL-pattern heuristic** (`/checkout /cart /payment
/login /signin /signup /register /contact /search`) runs before any LLM
call; only ambiguous URLs fall back to the LLM. A pattern match gets a
deterministic `business_risk_score=1.0` — no LLM judgment needed for a
definitive match.

**`llm_call_logs` gained three columns in Phase 2:** `is_mock` (bool),
`error` (Text, full exception + a raw-response snippet, capped at 8000
chars), `error_type` (small controlled vocabulary: `timeout`,
`rate_limited`, `http_error`, `json_decode_error`, `validation_error`,
`unknown`). Every real call logs a row — success or failure — per
CLAUDE.md's non-optional instrumentation rule; `error_type` is a clean
categorical field so failure-rate analysis (and Phase 4's planned
per-agent success% panel) is a `GROUP BY`, not string-parsing exception
names out of free text.

**Persistent cache was Reviewer-only in Phase 2** (`llm_response_cache`
table, keyed on sha256 of `agent + wcag_rule + normalized html_snippet`).
Normalization is deliberately conservative: whitespace collapse + tag/
attribute-name lowercasing only, never attribute values or text content
(several locked rules need real attribute values to reason correctly —
e.g. `color-contrast`'s inline colors, `html-lang-valid`'s `lang` value).
Verified live: an identical repeated violation showed `cache_hit=true`
with `latency_ms=0`/`tokens_used=0` on the second and third calls.

**Phase 3: cache extended to Developer.** `target_selector` was the only
real risk (instance-specific, unsafe to reuse verbatim across two
different violations) — but it's not independently generated content, the
Developer prompt tells the LLM to copy `element_selector` verbatim, so a
cache hit always overrides `target_selector` with the *current* call's
`element_selector` rather than trusting the cached value, fully
neutralizing the risk. Confirmed via a dedicated test
(`test_developer_cache_hit_overrides_target_selector`) and observed live:
a real second scan of the same page hit the Reviewer cache
(`cache_hit=true`). Impact's LLM-fallback is still not cached — it reasons
about the page URL, not the violating element, a different key shape
entirely — but is now routed to a smaller/cheaper model instead
(`IMPACT_FALLBACK_MODEL_NAME = "llama-3.1-8b-instant"`, verified live
against Groq's real API: HTTP 200, and its own independent 14400 req /
6000 token rate-limit budget, confirmed separate from `qwen/qwen3-32b`'s —
see Section 8b's per-model rate-limit-state update below). Reviewer and
Developer stay on `qwen/qwen3-32b` — fix-quality-critical steps untouched.

**`LLM_MOCK` env flag** returns canned, schema-valid responses instead of
calling Groq, for testing graph wiring/DB writes/API shape without
spending real quota. `is_mock` is never a parameter nodes pass — it's a
hardcoded literal inside `llm_client.py`'s two private dispatch functions,
so there's no code path where it could be set wrong. Verified live via the
real `/scan` endpoint with `LLM_MOCK=true`: 43/43 violations got mock
confidence/impact/fix, 129/129 `llm_call_logs` rows in that window showed
`is_mock=true`, zero real Groq calls made.

## 8b. Phase 2 addendum — rate-limit-aware pacing (added after Phase 2's own verification, not part of the original Phase 2 plan)

Running a real scan against 43 real violations (W3C's WAI "bad"
accessibility demo page) hit repeated Groq 429s almost immediately.
Reading the response headers revealed the real binding constraint:
**6,000 tokens/minute** (`x-ratelimit-limit-tokens`), not the ~60 RPM
figure Section 7's model-choice math was based on. At ~650 tokens/real
call, that's only ~9 sustainable calls/minute — without pacing, any scan
past a handful of violations would hit repeated 429s as the *common*
case rather than the occasional one the per-violation `try/except` was
designed to absorb, silently losing real violation coverage.

**Fixed immediately, not folded into Phase 3.** Phase 3's planned cost
optimization (caching, model routing) is about making *fewer* calls; this
is about not exceeding the rate of calls actually made — a different
problem, cheap to fix once understood, and not worth leaving broken for
every large-site test between now and Phase 3.

**Lives entirely in `backend/app/llm_client.py`**, not `run_scan`'s loop.
`_call_real` already sees every real response; `run_scan`'s loop operates
per-violation, but one violation can trigger 2-3 real calls across
Reviewer/Impact/Developer, so pacing has to apply between individual
calls, not between violations, or three back-to-back calls for one
violation could still blow the budget before the next violation's pacing
check ever ran.

**Adaptive, not fixed-delay.** Module-level state (`_remaining_tokens`,
`_reset_at_monotonic`) is updated from Groq's real headers after every
real call — success or 429, both carry them. Before a new real call, if
remaining tokens are below a safety margin (**1,500 tokens** — raised from
an initial 1,000 after seeing real Developer calls run up to 1,362
tokens, above that first margin) *and* a reset deadline is known, sleep
exactly until that deadline; otherwise proceed immediately with zero
delay. Runs calls back-to-back whenever there's genuine headroom.

**Phase 3 update: per-model, not per-account.** Now that Impact routes to
`IMPACT_FALLBACK_MODEL_NAME` (Section 8 above), `_remaining_tokens`/
`_reset_at_monotonic` became `dict[str, ...]` keyed by resolved model
name — confirmed live (not assumed) that Groq tracks the 6,000
tokens/minute budget independently per model: a same-second probe showed
`qwen/qwen3-32b` at 1000 req/6000 token limits and `llama-3.1-8b-instant`
at a completely separate 14400 req/6000 token limits, each decrementing
independently. A single shared budget would have either needlessly
throttled Impact's small-model calls using qwen3-32b's observed usage, or
vice versa.

**Also found live during Phase 3 verification: `reasoning_format:
"hidden"` is qwen3-specific, not a general Groq chat-completions
parameter.** Sending it with `llama-3.1-8b-instant` returns a hard 400
(`"reasoning_format is not supported with this model"`), not a graceful
ignore — reproduced directly (a real scan's Impact call failed this way
before the fix). `_call_real`'s payload now only includes
`reasoning_format` when `resolved_model == MODEL_NAME`.

**Concurrency-safe via one `asyncio.Lock`** (`_rate_limit_lock`) wrapping
the pace-check + real HTTP call + state update as one atomic sequence
(`_make_paced_request`). This project already runs concurrent scans via
FastAPI `BackgroundTasks` (Phase 1's documented no-shared-browser-pool
limitation) — without a lock, two concurrent scans could each read "budget
looks fine" before either updates the shared state. Serializing the
network call itself costs nothing real: Groq's own ceiling already caps
achievable throughput to ~9 calls/minute regardless of local concurrency.

**Failure handling is unchanged.** A 429 that still occurs despite pacing
(clock skew, a burst that slips through) is still caught by `_call_real`'s
existing `try/except` exactly as before Phase 2 — logged with
`error_type="rate_limited"`, that violation skipped cleanly. This is a
proactive layer in front of that handling, not a replacement for it.

**Deliberately not handled:** request-based limits
(`x-ratelimit-*-requests`). The *observed* bottleneck was tokens/minute,
not requests/minute — pacing for a constraint that wasn't actually hit
would be solving a problem not in evidence.

**Verified live, small scale:** two back-to-back calls with healthy budget
ran in ~1-1.5s each with no pacing delay; a third call correctly detected
only 35 tokens remaining (well under the margin) and slept 59.61s — the
exact real reset window Groq reported — before proceeding, successfully
avoiding a 429 that would otherwise have occurred at that budget level.

**Verified live, full scale — real before/after comparison, not an
estimate:** re-ran the same 43-violation W3C WAI "bad" demo page scan that
originally hit 43/43 failed violations unpaced. Paced result: **124 total
real calls, 118 succeeded, 6 failed (5 `rate_limited` + 1 `http_error`) —
exactly matching the 6 violations (of 43) that ended up without a
confidence score.** Every failed call maps to exactly one aborted
violation with zero downstream calls for it, confirming the "abort on
first failure, no partial state" design holds under sustained real load,
not just a single staged failure. Net: **100% → 14% violation failure
rate** from pacing alone.

*(First pass at this comparison used a wrong time window — a bare
timestamp compared against a `timestamptz` column got interpreted as UTC
by Postgres, pulling in hours of unrelated earlier testing and producing
an inflated, misleading 88-failure count. Caught and corrected before
reporting; the 124/118/6 figures above use the scan's actual
`started_at`/`completed_at` UTC bounds.)*

**Margin raised from 1,000 to 1,500 after this run:** Developer calls were
observed up to 1,362 tokens (Reviewer/Impact stay lower, ~400-980) — above
the original 1,000 margin, meaning some calls could see a "safe-looking"
remaining-token count that wasn't actually enough to cover a longer
Developer response, plausibly explaining part of the residual 6 failures.
1,500 clears the observed max with real headroom.

**Re-verified at the same full scale with the new margin — real numbers,
not left as a guess:** re-ran the identical 43-violation scan a third
time with `TOKEN_SAFETY_MARGIN=1500`. Result: **129/129 real calls
succeeded, 0 failures of any kind, 43/43 violations got full confidence/
impact/fix.** Up from 118/124 calls (95%) and 37/43 violations (86%) at
the 1,000 margin. Closes the loop this section opened: the residual
failures at 1,000 genuinely were a margin-sizing problem, not some other
unresolved issue.

## 9. Phase 5 guardrails (decided in Phase 2 planning, enforced when Phase 5 starts)

1. **Hard-refuse, not a warning:** the Phase 5 evaluation runner must
   check `LLM_MOCK` at startup and fail loudly if true — mock data
   silently entering real precision/recall/calibration numbers would
   violate CLAUDE.md's ban on invented metrics.
2. **Cache stays enabled during Phase 5** (no disable flag — forgetting
   to re-enable it is a real risk, and the cost savings matter more at
   30-50-site scale, not less). Instead, EVALUATION.md's confidence-
   calibration calculation must filter to `cache_hit=false` rows only: a
   cached judgment reused across pages is still correct for precision/
   recall, but treating N cache-hit copies of one real judgment as N
   independent samples would understate real variance and bias
   calibration numbers toward looking artificially consistent.
3. **Track and report the `error`/`error_type` failure rate per rule
   type** in EVALUATION.md. A violation whose reasoning failed never gets
   a confidence score and is silently absent from whatever sample Phase 5
   evaluates — if failures aren't uniform across rule types, the eval
   sample would be systematically biased without this being visible.

## 10. Phase 2.5 — Test suite + CI/CD design decisions

**Test-DB setup (2.5a):** a profile-gated `postgres_test` service added to
the existing `docker-compose.yml` (`profiles: ["test"]`, port 5434,
distinct `accessibility_agent_test` database) — not a
`docker-compose.override.yml`, since that file is already gitignored and
wouldn't be shared via git. A session-scoped autouse pytest fixture
(`backend/tests/conftest.py`) runs the real Alembic migration chain
against this test DB rather than a hand-built schema, enabled by a
one-line conditional guard added to `migrations/env.py`
(`if not config.get_main_option("sqlalchemy.url"): ...`) so a caller-set
`sqlalchemy.url` isn't clobbered back to dev. `.env.test` forces
`LLM_MOCK=true`, confirmed gitignored.

**Fixture/mock strategy (2.5b/c):** detector/crawler tests run against
static fixture HTML and a local stdlib `ThreadingHTTPServer`
(`backend/tests/fixtures/server.py`) — never a live site. Reasoning-layer
tests force a single-node LLM failure by monkeypatching
`llm_client._call_mock` at the module level: `call_llm()` resolves
`_call_mock` as a same-module global at call time, so patching the module
attribute intercepts it regardless of how `graph.py` imported `call_llm`,
with zero edits to `llm_client.py` itself. The Reviewer cache and
`error_type` classification (only reachable through `_call_real`, since
`LLM_MOCK` short-circuits before both) are tested by calling `_call_real`
directly with the sole network seam (`_make_paced_request`) monkeypatched
to return canned `httpx.Response` objects or raise — driving all 6 real
classification branches through genuine code, not re-implemented test
logic.

**A real, non-obvious infra bug found and fixed (2.5c):** `db.py`'s
module-level pooled engine (`pool_pre_ping=True`) is a singleton shared
across every test subpackage that imports `main`/`db` (both `api/` and
`graph/`), reused across many test-function event loops (pytest-asyncio's
default is a fresh event loop per test function). A pooled asyncpg
connection is bound to the loop that opened it; reusing one across a
different test's loop raised a raw `AttributeError` inside SQLAlchemy's
`pool_pre_ping` reconnect logic — the same failure class 2.5b already hit
and fixed for a different reason (switching a *test-only* verification
engine to `NullPool`). Since `db.py`'s engine is production code, not a
test file, the fix instead lives in `graph/conftest.py`: a test-only
autouse fixture that disposes `db.engine`'s pool both before and after
every test in that directory. Confirmed this quirk is specifically a
Windows `ProactorEventLoop` artifact — it never manifested on CI's
`ubuntu-latest` runner (Linux's default `SelectorEventLoop`), even though
the dispose fixture still runs there harmlessly.

**CI/CD pipeline (2.5d):** `.github/workflows/ci.yml`, triggered on every
push (any branch) and PRs into `main`, backend-only (no frontend code
exists yet). Key decisions:

- **Real `.env`/`.env.test` files, not job-level env vars.** Both are
  gitignored and don't exist in a fresh CI checkout. Initially tried
  job-level `env:` (functionally equivalent — `load_dotenv` no-ops
  harmlessly when the file's missing, real env vars pass through), but a
  real first-run failure changed this: `test_scan_roundtrip.py` (2.5b)
  reads `backend/app/.env` directly via `dotenv_values()` — a raw file
  parse, bypassing `os.environ` entirely — to prove a scan never touched
  the dev DB. That check needs the file to actually exist. Switched to
  writing real files, which also turned out to be the more faithful
  mirror of local dev (same code path, same mechanism) rather than a
  CI-only shortcut.
- **Two Postgres services, mirroring `docker-compose.yml` exactly**
  (`postgres` on 5433 = dev, `postgres_test` on 5434 = test), not one.
  The isolation check above needs a real, separate, queryable dev
  database — and since it queries a real `sites` table (expecting zero
  matching rows, not a missing table), Alembic runs against *both*
  databases in CI, not just the test one.
- **`ubuntu-latest`, not `windows-latest`.** Nothing in the app is
  Windows-specific. The stale-pooled-asyncpg-connection issue 2.5b/2.5c
  hit and worked around (`graph/conftest.py`'s dispose-before-and-after
  fixture) is a Windows ProactorEventLoop artifact specifically and
  doesn't reproduce on Linux's default SelectorEventLoop — confirmed by
  the CI runs going green without that workaround being CI-relevant at
  all (the fixture still runs, just never hits the failure mode it
  guards against).
- **An explicit, separate `alembic upgrade head` step**, even though
  pytest's own `run_migrations` fixture (`backend/tests/conftest.py`,
  session-scoped, autouse) already runs the real migration chain
  automatically. Technically redundant (idempotent — already-at-head is a
  no-op) but isolates "did the schema apply" from "did tests pass" in the
  Actions log, and runs before the slower Playwright/pytest steps.
- **`ruff` with zero custom config** (no `ruff.toml`/`pyproject.toml`).
  `ruff check backend/` with its built-in default rule selection
  surfaced exactly one real finding on the entire pre-2.5d codebase (an
  unused `import pytest` in a 2.5b test file) — sufficient to satisfy
  CLAUDE.md's "lint" promise without inventing a broader style migration
  nobody asked for.
- **Proven, not assumed, to actually gate real regressions**: a
  deliberately reintroduced unused-import violation on a throwaway commit
  produced a real `conclusion: "failure"` at the Lint step specifically
  (downstream steps skipped), reverting it produced a real
  `conclusion: "success"` with the same 41-pass count as local — same
  "prove the gate works" standard used throughout Phase 2.5, applied to
  CI itself (see PR #11, runs `28919211909` red / `28919267276` green).

**Verify & close (2.5e):** one consolidated proof that the *whole*
pipeline — not an individual test or the lint step alone — protects
Phase 3, distinct from every prior proof (which were either local or
lint-only): reintroduced the real Phase 1 datetime-tz bug
(`_TZ_DATETIME` reverted to `DateTime(timezone=False)` + a throwaway
migration) on a real PR (#12). Real CI red (run `28920503993`): **12
failed, 29 passed** — wider than planning assumed, because
`_TZ_DATETIME` is one shared constant used by every timestamp column
across `models.py`, not just the one migration this session altered;
confirmed via the real generated SQL in the CI log
(`llm_call_logs` inserts also cast `created_at` as
`::TIMESTAMP WITHOUT TIME ZONE`). Reverted (confirmed byte-clean via
`git diff` against the pre-regression commit); real CI green (run
`28920679468`): 41 passed. PR #12 closed unmerged (nothing to merge —
branch was byte-identical to `main` after the revert).

Branch protection added on `main` (explicit decision, confirmed with you
— a real repo-settings change, not a code change): `required_status_checks`
requires the `test` check, `strict: true`, `enforce_admins: true`,
`allow_force_pushes: false`. Confirmed via the GitHub API that no
protection existed beforehand (`404 "Branch not protected"`).

## 11. Phase 4 — Dashboard + verified fixed-page delivery

Phase 4 deliberately changed the shape of the "human approval" step from
what Section 5's original architecture diagram assumed (`Approve → PyGithub
→ real PR`). Decided during planning, before any code was written:

**No PyGithub/real PR in Phase 4.** Most scanned sites (`usa.gov`,
`news.ycombinator.com`, ...) aren't GitHub repos at all — there's nothing
to fork/push to. Real PR creation is deferred to Phase 6 (optional,
already scoped there as its own fiddly chain against one real chosen
target), not invented generically now. `approvals.pr_url`/`pr_status`
remain in the schema, unused, for Phase 6 to populate later.

**The real deliverable is a verified fixed copy of the page.** A human
approves fixes on a page (`POST /fixes/{id}/approval`, per-fix grain,
matching the existing schema) → `page_fixer.py` combines every approved,
individually-verified fix onto one copy of the page
(`POST /pages/{id}/generate-fixed-page`) → the full detector reruns once
on the combined result → if clean, `GET /pages/{id}/download-fixed` serves
it (optional click, never a forced download).

**Live-page drift between verification and generation, resolved.**
Verification happens at scan time; human approval — and therefore
generation — can happen minutes, hours, or days later. If generation
reloaded the live site fresh at that point, the combined fix could get
applied to different content than what was actually verified, silently.
Resolved by having `page_fixer.apply_verified_fixes_to_page()` apply fixes
to the page's already-captured `raw_html_snapshot_path` via
`page.set_content()`, never a fresh `page.goto()` — anchoring generation to
the same scan run's content regardless of approval delay. This doesn't
guarantee byte-identical content to whatever `verify_fix()`'s own live
reload saw seconds-to-minutes earlier in the same scan (a smaller,
pre-existing Phase 3 imprecision) — it eliminates the much larger gap
Phase 4's human-approval delay would otherwise introduce. Proven directly
in `test_page_fixer.py::test_ignores_live_page_content_uses_snapshot_only`
— `page_url` points at a domain that will never resolve, yet combination
still succeeds, since the live URL is never fetched, only stitched into a
`<base href>` string.

**`html-has-lang`/`html-lang-valid` hardened as a prerequisite.** These two
rules' `target_selector` is the `<html>` element itself. Before Phase 4,
fixing them the same way every other rule is fixed (full outerHTML
replacement) would have forced the Developer LLM to regenerate the entire
page just to set one attribute — real truncation risk — and, once multiple
fixes started being combined onto one page (the whole point of this
phase), applying it would silently overwrite every other already-applied
fix on the page. Fixed by special-casing these two rule IDs to a targeted
`el.setAttribute('lang', ...)` call instead
(`verifier.apply_fix_to_locator`, shared by both `verify_fix()` and
`page_fixer.py`), with the Developer agent's rule guidance changed to
return only the bare language code as `proposed_code_diff`, not markup.
Regression-proven combined with an unrelated fix on the same page in
`test_page_fixer.py::test_combines_lang_fix_with_unrelated_fix_clean` —
the exact scenario this hardening exists for.

**Partial approval is allowed, explicitly, not silently.** If only some of
a page's fixes are approved, `generate-fixed-page` still proceeds with
whatever is approved (requiring at least one), and its response always
reports `fixes_included_count`/`fixes_pending_count` — the frontend's
"Generate partial fix (N/M approved)" label reads directly from this,
never presenting a partial result as complete.

**CORS is scoped, not wildcarded.** `FRONTEND_ORIGIN` (default
`http://localhost:5173`) is the only allowed origin — this project has no
auth/multi-tenancy layer, so an open CORS policy would have nothing else
guarding it.

**Accessibility score trend — a definition introduced, not discovered.**
Nothing in schema.md defined an "accessibility score" before Phase 4.
Confirmed definition: `count(open violations) / count(pages)` per scan,
trended across a site's repeat scans by `scans.completed_at` — a direct
ratio of two already-logged counts, no invented weighting or composite
formula, lower is better.

**Known, documented limitation — the downloaded fixed page is a frozen
snapshot.** Detection and fix-verification already operate on the live,
post-JS-render DOM (a real Playwright browser, `wait_until="networkidle"`)
so JS-heavy sites are handled correctly for *those* two things — this was
already true before Phase 4. The *downloaded* fixed page
(`page.content()` after combination) is a frozen snapshot, though: a
client-rendered SPA that re-hydrates on load could silently overwrite the
injected fix the moment its own JS runs again, and relative asset paths in
the snapshot were relative to the *original* page's URL. Mitigated, not
solved: a `<base href="{page_url}">` tag is injected before combination
(so relative CSS/JS/images at least resolve against the real origin,
needed for accurate rendering during the combined detector rerun too, not
just the download) — full SPA-hydration-safe standalone redeployment is
out of scope, the same way BackgroundTasks' non-durability (Section 4f) is
a documented tradeoff rather than a solved problem.

**Null `raw_html_snapshot_path` handling, closed after review.** This
column has been nullable since Phase 1 (only set for `status="loaded"`
pages), and `page_fixer.py` is a new, second consumer of it beyond its
original use. `main.py`'s `generate_fixed_page` endpoint already guarded
against a null value (400), but `page_fixer.py` itself did not — its
`except OSError` around `Path(raw_html_snapshot_path).read_text(...)`
does not catch the `TypeError` `Path(None)` actually raises, confirmed
directly (`Path(None).read_text()` → `TypeError`, not `OSError`),
breaking the module's own "never raises" contract for that one input if
ever called without `main.py`'s guard in front of it. Fixed with an
explicit `if not raw_html_snapshot_path:` check before constructing a
`Path` at all, with real tests at both layers (module-level: a direct
call with `raw_html_snapshot_path=None` returns a structured error, not
an exception; endpoint-level: a page with `status="loaded"` and a null
snapshot path returns a clean 400).

**Containerization completed for real, not just extended.** Neither the
backend nor the frontend had a `Dockerfile` before Phase 4 — only Postgres
was containerized, despite CLAUDE.md's stated "frontend + backend +
Postgres only" scope. Both were added this phase: `backend/Dockerfile`
(Python 3.14, `playwright install --with-deps chromium` matching
`ci.yml`'s own step exactly, an entrypoint that runs `alembic upgrade
head` before serving so `docker compose up` is self-contained) and
`frontend/Dockerfile` (Node, `vite preview` — appropriate for this
project's "clickable demo" scope, not a hardened production serve).
`VITE_API_BASE_URL` is baked in at frontend build time as
`http://localhost:8000` deliberately, not the Docker-internal
`http://backend:8000` — the frontend runs client-side in the host's
browser, which can't resolve Docker-internal service names.

Full narrative in `PHASE4_COMPLETION_REPORT.md`.

## 12. Phase 4.5 — Frontend testing + CI/CD

Fills in `PLAN.md`'s Phase 4.5 placeholder ("decided when this phase
starts, not now") now that real frontend code exists. Same "raise the
decision, write the reasoning down" discipline Section 10 used for the
backend's Phase 2.5 CI/CD work.

**Tooling: Vitest + React Testing Library, no MSW.** Vite-native, shares
the existing `vite.config.ts` transform pipeline — no alternative
seriously considered since nothing existed to substitute *from*.
`api/client.ts`'s exported functions (or, for page-level tests, the
`useScanSelector` hook itself) are mocked directly via `vi.mock`, mirroring
the backend's own preference (Section 10) for monkeypatching the real
seam over a heavier mocking framework.

**Config kept separate** (`frontend/vitest.config.ts`, not a merged `test`
block in `vite.config.ts`), matching this project's existing dev/test
separation pattern (`.env`/`.env.test`, distinct Postgres services).

**Tests colocated** (`Component.test.tsx` next to `Component.tsx`), not a
mirrored `frontend/tests/` tree like the backend's own convention — at
~11 test files, duplicating the `components/`/`pages`/`hooks`/`api`
directory structure wasn't worth the indirection, and colocation is the
standard Vitest/RTL pattern. `tsconfig.app.json`'s `include: ["src"]`
already covered it with zero config changes.

**A real gap found while wiring up `setupTests.ts`, not just a config
nit.** With `globals: false` (explicit `import { expect } from "vitest"`
everywhere, consistent with `verbatimModuleSyntax`), React Testing
Library's auto-cleanup never self-registers — it only activates when it
detects a *global* `afterEach` (jest, or Vitest's `globals: true`). Every
test after the first in a file was seeing leftover DOM from prior tests
(duplicate badges, stale SVGs, miscounted bars) until an explicit
`afterEach(cleanup)` was added to `setupTests.ts`.

**A real production bug found and fixed, not just a testing gap
(R1).** `useScanSelector.ts`'s site→scans effect and `refetchScan` both
fired a fetch with no check, on resolution, that the response still
matched the current selection. Rapid reselection (scan A, then scan B
before A resolved) could let A's late response silently overwrite B's
already-rendered state. Confirmed via a direct grep of `frontend/src` for
any staleness guard (`AbortController`/`cancelled`/etc.) — zero matches.
Fixed before writing the test that would otherwise have just locked in
the bug: the site→scans effect uses an effect-cleanup `cancelled` flag;
`refetchScan` uses a ref-based "latest request" token instead, since it's
also invoked imperatively by `ReviewApproveView`/`ViolationsView` outside
the effect that originally triggered it. Landed as its own commit
(`5fb7783`), separate from every test file, called out explicitly rather
than folded silently into a nominally "add tests" phase. Regression
tests: `useScanSelector.test.ts`'s two "guards against a stale ... response"
tests fire two overlapping requests with the second resolving first, and
assert the hook's state reflects the second (current) selection.

**Async test convention, standardized once.** All loading→error→success
assertions use RTL's `findBy*`/`waitFor`, never a manual `act()` wrapper —
documented as a comment in `setupTests.ts` during the first checkpoint so
every later test file follows the same pattern instead of improvising.

**`oxlint` was already part of the Phase 4 scaffold**, not new tooling
introduced here — confirmed via `package.json`'s existing `"lint": "oxlint"`
script and the existing `.oxlintrc.json`. The CI job's lint step just
wires up what Phase 4 already configured.

**CI: an independent `frontend` job in the existing `ci.yml`**, parallel
to `test`, no Postgres/backend services — the frontend suite mocks
`api/client.ts`, never hits a real backend, so the job has nothing to
wait on. `actions/setup-node@v4` (22.x) → `npm ci` → `oxlint` → `tsc -b`
→ `vitest run` → `vite build`.

**Regression proof, same standard as Phase 2.5e, tightened to the exact
assertion.** `ReviewApproveView.tsx`'s `combined_verification_status ===
"clean"` gate (the check controlling whether the download link renders)
was inverted to `!==`, on real pushes to the `phase-4.5` branch — not a
hypothetical. Red run
[29124818143](https://github.com/SiddhiKhairee/accessibility-compliance-agent/actions/runs/29124818143):
`frontend` job failed at the Vitest step with exactly the 3
`ReviewApproveView.test.tsx` download-gating tests failing (`renders the
download link when ... 'clean'`, `does NOT render ... 'violations_remain'`,
`does NOT render ... null`) — all 9 other tests in that file and every
other test file stayed green, and the backend `test` job was unaffected
(frontend-only change). Reverted (confirmed byte-clean via `git diff`
against the pre-regression commit); green run
[29124965399](https://github.com/SiddhiKhairee/accessibility-compliance-agent/actions/runs/29124965399):
both jobs passing.

**Branch hygiene note.** The R1 fix was accidentally committed directly to
local `main` before a `phase-4.5` branch existed. Caught and corrected
before any push: `phase-4.5` created at that commit, local `main` moved
back to `origin/main` (confirmed identical via `git fetch` + `git log
origin/main..main`/`main..origin/main`, both empty, before touching
anything). Final commit order on `phase-4.5` is R1-fix-first rather than
interleaved with the Checkpoint 1 tooling commit, by explicit choice
(avoids a history-rewriting `git reset` for a cosmetic reordering) — still
separate, non-squashed commits for each unit of work (R1 fix; tooling+
component tests; hook+client tests; page tests; CI extension; regression-
proof push + revert).

Full narrative in `PHASE4_5_COMPLETION_REPORT.md`.

## 13. Phase 5 — Pass 1a execution: design decisions, real-world validation, and known limitations

Documents the real crawl-only Pass 1a run against the 30-site corpus
(`eval/eval_corpus_30_sites.csv`) and everything it surfaced — a design
decision that predates the run, a real-world validation of Phase 4.6, a
new debugging gotcha, and two standing limitations. Same discipline as
Section 12: real evidence, gaps stated explicitly, not glossed over.

**13a. Pass 1a/1b split as a design decision.** Crawling (Pass 1a) runs to
completion across the whole corpus regardless of budget; Reviewer scoring
(Pass 1b) is budget-gated and can stop mid-corpus without finishing every
site. Reasoning: crawling has zero Groq cost, while Reviewer calls are the
real constrained resource — `EVAL_DAILY_CALL_CAP` defaults to 1000
requests/day with a 0.9 safety margin (`config.py`; see Section 9's
guardrails). If crawling and review were interleaved per-site instead, a
violation-heavy site early in corpus order could exhaust the daily budget
before later sites in the corpus were ever crawled at all — starving them
of even the free stage. Splitting the two into sequential loops means a
crawl-only run can always get real violation counts for the *entire*
corpus first, independent of how much Reviewer budget is available or
already spent.

Mechanism: `eval_runner.run_pass1()` runs a full crawl loop over every
corpus site not yet `crawl_detect_status: "done"`, then a separate review
loop over every violation not yet reviewed, checking the daily-budget
guard before each real Reviewer call. A `review_enabled: bool = True`
parameter (`review_enabled=False` for a crawl-only run) returns cleanly
right after the crawl loop, before the review loop starts at all — zero
`reviewer_node` calls, zero Groq spend. Both loops checkpoint into the
same resumable `progress_pass1.json` manifest (atomic writes: tmp file +
`os.replace`), so a run that stops partway — crash, a hung site, an
intentional crawl-only stop — resumes from exactly where it left off
without re-crawling already-`done` sites or re-reviewing already-scored
violations.

**13b. Phase 4.6 bot-block handling — validated with real Pass 1a
numbers.** Section 4b already documents the block-detection mechanism
(`BLOCKED_STATUS_CODES`, `CHALLENGE_MARKERS`) and that it was unit tested.
This adds real corpus evidence. Of the 9 sites flagged ahead of time as
bot-protection-risk (booking.com, walmart.com, target.com, zillow.com,
tripadvisor.com, etsy.com, wayfair.com, forever21.com, expedia.com), the
current manifest shows 4 with an unambiguous, correctly-caught block
signal: expedia.com (`blocked (status 429)`), etsy.com and tripadvisor.com
(`blocked (status 403)`) — real HTTP-level blocks, `status="failed"` with
an accurate `failure_reason`, never scanned as if the block response were
real content. target.com and booking.com both loaded genuine, non-
challenge content — correctly *not* flagged. Verified directly for
target.com by inspecting the saved snapshot HTML: real page title, 111
`data-test=` attributes, genuine product markup, no CAPTCHA/interstitial
markers.

**Stated plainly, not glossed over:** the remaining bot-risk sites
(walmart.com, wayfair.com, zillow.com, forever21.com) currently show a
plain `Page.goto: Timeout ... exceeded` rather than a clean block signal.
Phase 4.6's detection only fires once a response or rendered HTML is
actually reached — a site that blocks by simply stalling the connection
indefinitely produces the exact same failure signature as the unrelated
`networkidle` timeout limitation documented in 13d. Current instrumentation
cannot tell these apart. This is a real, open gap in the bot-block
detection's coverage, not a solved case being narrated as one.

**13c. Methodology gotcha — naive `file://` snapshot reproduction silently
breaks CSS.** New standing debugging note, same category as the datetime-
timezone bug and the BackgroundTasks limitation (Section 4f): replaying a
previously-saved snapshot locally via `file://` navigation, without
disabling Chromium's file-origin CORS restrictions, gets a real axe-core
execution but visibly *unstyled* content — a silent false negative for any
rule that depends on actual rendered styling (`color-contrast` above all).

Real reproduction sequence (investigating why target.com's Pass 1a crawl
showed 0 violations): attempt 1 loaded a saved target.com snapshot via
plain `file://` navigation with no special launch args. Chromium's
file-origin restrictions blocked every cross-origin CSS request — ~226
CORS/`net::ERR_FAILED` console errors — and axe-core reported 0 violations
*and* 0 incomplete results against the effectively-unstyled page. Attempt
2 relaunched Chromium with `--disable-web-security
--allow-file-access-from-files` and reloaded the identical snapshot file —
real CSS loaded this time, confirmed via `getComputedStyle(document.body)`
matching target.com's actual brand styling (`font-family:
"Helvetica for Target", ...`, `color: rgb(51, 51, 51)`, not browser
defaults). With real styling applied, axe-core reported 1 real `incomplete`
`color-contrast` result (`impact: "serious"`, 2 nodes) — completely
invisible in attempt 1. This is the finding that fed the `color-contrast`
`REVIEW_ON_FAIL_RULE_IDS` addition documented in Section 2 (Phase 2.6 Part
1/2) — see that section for the fix itself, not repeated here.

**Correct procedure going forward:** always relaunch Chromium with
`--disable-web-security --allow-file-access-from-files` when replaying a
saved snapshot via `file://`, and verify styling actually applied with a
computed-style spot-check before trusting a "0 violations" result from a
local reproduction — a clean-looking zero can mean "genuinely no
violations" or "the page never got its CSS," and only the second one is
silent.

**13d. Standing limitation — `networkidle` page loading fails on
continuously-polling pages, and a longer timeout doesn't reliably fix it.**
Section 4b documents choosing `networkidle` over `load`/`domcontentloaded`
to make sure JS-rendered content is present before detection runs. The
real corpus run surfaced its cost: pages with continuous background network
activity — live score/content updates, ad refresh, analytics beacons — may
never go idle at all, regardless of timeout length, and time out on the
very first (root) page before the crawler ever discovers any further links
to queue.

Real before/after numbers from a targeted retry (10000ms -> 25000ms,
3 sites only — target.com, bbc.com, espn.com):
- target.com: 1/15 -> 8/15 pages loaded, 79 real violations recovered —
  the timeout value was genuinely the cause here, meaningfully improved.
- espn.com: 1/15 -> 4/15 pages loaded, 442 real violations recovered — but
  11 of 15 pages still exceeded even the 25s timeout. Partial, not
  resolved.
- bbc.com: 1/15 -> 0/15 — no recovery at all. The root page appears to
  never reach `networkidle`, most likely continuous live-content/ad
  polling that never lets the connection count drop to zero. A bigger
  timeout number did not help.

**This is broader than the 3 retried sites.** Of the 30 corpus sites, 14
currently have zero loaded pages. 4 of those are the legitimate,
correctly-handled bot-blocks from 13b. The other **10** — bbc.com,
walmart.com, wayfair.com, imdb.com, nytimes.com, stackoverflow.com,
medium.com, zillow.com, weather.com, forever21.com — show this identical
root-page `networkidle` timeout signature. Only 3 of these 10+ sites have
been retried at a longer timeout so far (this session, scoped
deliberately); the other 7 remain unretried and undiagnosed. Fixing this
properly likely needs a different wait strategy entirely (e.g. `load` plus
an explicit content-ready check, or a capped hybrid fallback) rather than
a bigger timeout number — `bbc.com`'s result at 2.5x the original timeout
is direct evidence that timeout tuning alone has a ceiling. Not attempted;
stated here as a real, currently-unresolved limitation.

**13e. New `page_load_timeout_ms` opt-in parameter.** `crawler.crawl_site()`
and `eval_runner.run_pass1()` both gained a `page_load_timeout_ms`
parameter, defaulting to the existing `crawler.PAGE_LOAD_TIMEOUT_MS`
(10000ms) — behavior is unchanged for every existing caller and every
future run that doesn't explicitly pass a different value. Purpose:
targeted recovery retries against specific already-crawled sites (as used
for the 3-site retry in 13d) without touching the timeout used for the
other 27+ sites or any future full-corpus run. Raising the *default*
timeout for all sites is a separate decision this addition deliberately
does not make.

**13f. Corpus coverage honesty note.** All 30 corpus sites show
`crawl_detect_status: "done"` — but "done" means "a crawl attempt
completed and was recorded," not "usable page data was obtained." Real
current numbers: 240 page-attempts recorded across the corpus, 178 loaded
(74% of attempts) — but that 178 is concentrated in only **16 of the 30
sites**; the other 14 sites currently contribute zero page-level violation
data (4 legitimate bot-blocks per 13b, 10 unresolved `networkidle` timeouts
per 13d). 3,122 total violations are recorded corpus-wide, and every one
of them is still `reviewer_status: "pending"` — Pass 1b has not run. "30
sites" should not be read as "30 sites' worth of uniform data" —
EVALUATION.md's methodology section should cite this note rather than
re-derive or re-explain it.
