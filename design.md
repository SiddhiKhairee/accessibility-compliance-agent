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
| 4 | Keyboard (2.1.1) | tabindex checks, keyboard traps |
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
