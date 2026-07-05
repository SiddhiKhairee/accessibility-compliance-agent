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
crawler never logs in or holds a session. Pages that require auth simply
fail to load as expected (redirect, 403, etc.) and are handled by the same
skip+log path as any other failed page — no separate "is this page
authenticated" check was needed.

**Failure handling matches the CLAUDE.md hard rule:** each page load has
its own timeout (10000ms, `networkidle` — see Section 4c) and a failed page
is logged with a `failure_reason` and skipped, never crashing the rest of
the crawl. Verified directly: python.org's homepage times out on
`networkidle` (likely persistent background connections) and the crawler
reported `0/1 pages loaded successfully` cleanly instead of raising.

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
