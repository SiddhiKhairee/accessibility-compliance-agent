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

**`bypass` and `duplicate-id-aria` (2.4.1 / 4.1.2) can never surface as a
`Violation` row under the current detector.py, even though they're locked
v1 rules.** Discovered during Phase 2.5b regression-test fixture
verification (not previously documented): axe-core marks both rules
`reviewOnFail: true` in its own rule metadata, meaning a genuine failure of
either lands in axe's `incomplete` result array, not `violations`.
`detector.py`'s `detect_violations()` only reads
`results.response["violations"]`, so no fixture — however constructed —
can make either rule appear in its output. Confirmed directly: a fixture
page with no skip-link/heading/landmark, and a fixture with a duplicate id
referenced via `aria-labelledby`, were both run through a raw axe call and
genuinely failed, landing in `incomplete` each time (see
`backend/tests/detector/test_detector.py`'s
`test_bypass_known_gap_never_surfaces_as_a_violation` and
`test_duplicate_id_aria_known_gap_never_surfaces_as_a_violation`, which
codify this as current, observed behavior rather than silently ignoring
it). Not fixed in 2.5b — that session was scoped to regression tests for
existing behavior, not new detector logic. A real fix would mean also
reading axe's `incomplete` array for `reviewOnFail` rules (at minimum for
these two); flagged here so Phase 3+ doesn't build fix/verification logic
that implicitly assumes all 9 locked rules are reachable, and so Phase 5's
EVALUATION.md doesn't report coverage numbers for these two rules that
overstate what the detector can actually surface.

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
Reviewer → Impact → Developer → Verifier → END. Verifier is a structural
stub in Phase 2 (returns `status="pending_verification"`, no LLM call, no
Playwright re-check) — Phase 3 fills in the real apply-fix-and-reverify
logic without restructuring the graph.

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

**Persistent cache is Reviewer-only** (`llm_response_cache` table, keyed
on sha256 of `agent + wcag_rule + normalized html_snippet`). Not used for
Developer (its output carries an instance-specific `target_selector` —
reusing a cached response across two different violations would hand one
violation another's selector) or Impact's LLM-fallback (which reasons
about the page URL, not the violating element — a different key shape
entirely). Both deferred to Phase 3's real cost-optimization scope.
Normalization is deliberately conservative: whitespace collapse + tag/
attribute-name lowercasing only, never attribute values or text content
(several locked rules need real attribute values to reason correctly —
e.g. `color-contrast`'s inline colors, `html-lang-valid`'s `lang` value).
Verified live: an identical repeated violation showed `cache_hit=true`
with `latency_ms=0`/`tokens_used=0` on the second and third calls.

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

**Test-DB setup, fixture/mock strategy (2.5a/b/c):** full reasoning lives
in PLAN.md's Phase 2.5a/b/c session-log entries (profile-gated
`postgres_test` service vs. a docker-compose override file, the Alembic
`env.py` caller-set-`sqlalchemy.url` guard, `_call_mock`-monkeypatch fault
injection, the Windows-ProactorEventLoop stale-pooled-connection fix). Not
duplicated here — a full design.md rewrite of Phase 0-2.5c is 2.5e's
explicit job ("update CLAUDE.md/PLAN.md/design.md to reflect what was
actually built"), not this entry's.

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
