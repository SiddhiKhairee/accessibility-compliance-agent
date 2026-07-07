# Phase 2 Completion Report — Multi-Agent Reasoning Layer

Built interactively in Plan Mode per CLAUDE.md's workflow (`Start each
phase in Plan Mode. Confirm the approach before writing code.`). The
approved plan is at `C:\Users\siddh\.claude\plans\delegated-sniffing-lollipop.md`.
**PLAN.md and design.md have already been updated** (checkboxes, session
log, Sections 7-9) — this report is the fuller account of what happened,
including the parts that didn't go as originally planned. **Updated after
the fact with Section 11**, covering a real Phase 2 addendum (rate-limit
pacing) added once Phase 2's own verification surfaced a problem serious
enough to fix immediately rather than defer.

## 1. The plan changed mid-flight — this is the headline of Phase 2

Phase 2 did not ship what CLAUDE.md originally specified. The tech stack
line said `LLM: local via Ollama (zero cost)`. That's no longer true, and
the change is logged, not silent:

| Step | What was planned | What actually happened |
|---|---|---|
| Initial plan | Local Ollama, `qwen2.5:7b-instruct` | Never installed — see Step 0 gate below |
| Readiness check | — | Found only ~2.2GB RAM free of 16GB (Docker WSL VM, IDE, browsers already using the rest) — a local 7B model's ~5.5-6.5GB footprint was a real swap-thrashing risk, not a hypothetical one |
| Alternative evaluated | — | Cerebras free tier — checked directly against `inference-docs.cerebras.ai`, not aggregator blogs. No Qwen model on its catalog; 5 RPM cap too slow |
| Model benchmark | — | Real side-by-side test on Groq's free tier: `qwen/qwen3-32b` vs `openai/gpt-oss-120b`, same real usa.gov violation. Identical quality (0.95 confidence both). Chose qwen3-32b: gpt-oss's 30 RPM cap is tighter than its own real speed (856ms/call), wasting the speed advantage; qwen3-32b's 60 RPM cap is looser than its own real speed (1456ms/call), so its real bottleneck is latency, not the cap — nets more effective throughput |
| Structured output | Assumed usable for schema-guaranteed output | Checked Groq's docs directly: strict `json_schema` mode is **only available on gpt-oss-20b/120b**, not qwen3-32b. Kept qwen3-32b anyway, switched to non-strict `json_object` mode + real Pydantic validation as the correctness backstop |
| Rate-limit model | Assumed RPM (60/min) was the binding constraint | **Wrong — discovered live, not predicted.** Groq's real constraint for this account is **6,000 tokens/minute** (`x-ratelimit-limit-tokens` header). At ~650 tokens/call that's ~9 sustainable calls/min, far tighter than the ~41/min the RPM-only math predicted |

This is exactly the kind of tech-stack substitution CLAUDE.md says to flag
rather than quietly swap in — CLAUDE.md's own LLM line has been edited to
match (diff below), with the full reasoning trail kept in the plan file
rather than only in this report.

## 2. Step 0 gate (dependency/tooling check)

| Dependency | Status before | Action |
|---|---|---|
| Ollama | Not installed anywhere on this machine (not in PATH, no Program Files/AppData install, nothing on :11434) | **Not installed — abandoned in favor of Groq (see Section 1)** |
| `langgraph` | Absent | Installed `1.2.8` |
| `httpx` | Absent | Installed `0.28.1` (used directly for Groq calls — no `groq` SDK, no `langchain-groq`; a full SDK was unneeded weight for one REST endpoint) |
| `GROQ_API_KEY` | Already present in `backend/app/.env` | Confirmed present via existence check, value never printed. **Note:** an earlier key was pasted into chat during model-comparison testing and has since been rotated by the user independently — no action needed from this session |
| Docker Postgres | Up and healthy from Phase 1 | Unchanged, still healthy 26+ hours uptime |

## 3. Files created/changed

New: `backend/app/graph.py`, `backend/app/llm_client.py`,
`backend/app/agents/{__init__.py, reviewer/, impact/, developer/, verifier/}`
(prompt.py + schema.py per agent, no prompt.py for verifier — it's a
structural stub with no LLM call), `backend/migrations/versions/347a304e5105_*.py`.
Updated: `CLAUDE.md` (LLM stack line), `backend/app/models.py` (3 new
`llm_call_logs` columns, new `LlmResponseCache` model, `Violation` ↔
`ImpactAssessment`/`Fix` relationships), `backend/app/main.py` (`run_scan`
reasoning pass, `ImpactAssessmentOut`/`FixOut` response models),
`backend/app/config.py` (`GROQ_API_KEY` setting), `requirements.txt`
(`langgraph`, `httpx` + transitive deps), `PLAN.md`, `design.md`.

## 4. Migration (final content)

Revision `347a304e5105`, applied cleanly against the empty (0-row)
`llm_call_logs` table — no backfill needed since Phase 2 is the first
phase to write to it.

```python
def upgrade() -> None:
    op.create_table('llm_response_cache',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('wcag_rule', sa.String(length=100), nullable=False),
    sa.Column('cache_key', sa.String(length=64), nullable=False),
    sa.Column('response_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_llm_response_cache_cache_key'), 'llm_response_cache', ['cache_key'], unique=True)
    op.add_column('llm_call_logs', sa.Column('is_mock', sa.Boolean(), nullable=False))
    op.add_column('llm_call_logs', sa.Column('error', sa.Text(), nullable=True))
    op.add_column('llm_call_logs', sa.Column('error_type', sa.String(length=50), nullable=True))
```

`llm_response_cache` is deliberately Reviewer-only (see Section 6).

## 5. CLAUDE.md diff

```diff
-- LLM: local via Ollama (zero cost — note latency/quality tradeoffs if relevant)
++ LLM: `qwen/qwen3-32b` via Groq's free-tier API (`reasoning_format:
++   "hidden"`, `response_format: {"type": "json_object"}`). Changed from the
++   original local-via-Ollama plan in Phase 2 planning: this machine has only
++   ~2.2GB RAM free of 16GB, making a local 7B+ model a real swap-thrashing
++   risk alongside Docker/Postgres/Playwright. Genuinely free (no card,
++   verified against Groq's own docs), but is a third-party API — page
++   HTML/violation content leaves the machine. Full reasoning logged in
++   the plan file.
```

## 6. Architecture decisions worth restating plainly

- **Exactly 4 LangGraph nodes** (`graph.py`): Reviewer → Impact → Developer
  → Verifier → END, linear edges, no branching. Verifier is a **structural
  stub only** — returns `status="pending_verification"`, no LLM call, no
  Playwright re-check. Phase 3 fills in the real logic without touching
  graph topology.
- **Nodes never touch the database.** They're pure functions over a
  shared state dict. `run_scan` invokes the graph once per open violation
  and commits `violations.confidence` + one `ImpactAssessment` + one `Fix`
  together, in a single transaction, **only if all 4 nodes succeed**. A
  failure anywhere (timeout, 429, malformed JSON, schema-validation
  failure) propagates out of `ainvoke()` before any write happens for that
  violation — no partial rows are possible by construction.
- **Persistent cache is Reviewer-only**, not Developer or Impact.
  Developer's output carries an instance-specific `target_selector` —
  reusing a cached response across two different violations would hand
  one violation another's selector. Impact's LLM-fallback reasons about
  the page URL, not the violating element, so the same cache-key shape
  doesn't apply. Both deferred to Phase 3's real cost-optimization scope.
  Cache-key normalization is deliberately conservative (whitespace
  collapse + tag/attribute-name lowercasing, never attribute values) —
  correctness over hit-rate, since several locked rules need real
  attribute values to reason about correctly.
- **`is_mock` can't be set wrong.** It's not a parameter nodes pass — it's
  a hardcoded literal inside `llm_client.py`'s two private dispatch
  functions (`_call_mock`/`_call_real`), so there's no code path where a
  node could pass the wrong value.
- **`error_type` is a small controlled vocabulary** (`timeout`,
  `rate_limited`, `http_error`, `json_decode_error`, `validation_error`,
  `unknown`), kept separate from the free-text `error` column so
  failure-rate analysis is a `GROUP BY`, not string-parsing exception
  names — this directly feeds Phase 4's already-planned per-agent
  success% dashboard panel, not new scope invented for this phase.

## 7. Raw verification output

**Real scan, real violations, real reasoning** — W3C's own "bad
accessibility" demo page (`w3.org/WAI/demos/bad/before/home.html`, a real
public page built specifically to contain violations for testing a11y
tooling), scan_id 9, 43 real violations detected by Phase 1's detector.

Full 4-node success on violation 778 (real `color-contrast` violation):
```
reviewer_result: confirmed=True confidence_score=0.98 reasoning="The reported
  contrast ratio (3.88) falls below the WCAG 2.1 minimum requirement of 4.5:1..."
impact_result: is_critical_path=True business_risk_score=0.8 reasoning_text=
  "The homepage is part of primary navigation, a core user task..."
developer_result: proposed_code_diff='<font color="#33454f" size="2"><b>Free
  Penguins</b></font>' target_selector='tr[height="25px"]:nth-child(2) >
  td[bgcolor="#A9B8BF"][width="150px"] > font[color="#41545D"][size="2"] > b'
verifier_result: status='pending_verification'
```
Confirmed persisted correctly via direct `psql`:
```
 id  |   wcag_rule    | confidence
-----+----------------+------------
 778 | color-contrast |       0.98

 violation_id | is_critical_path | business_risk_score | reasoning_text
          778 | t                | 0.8                  | (real text above)

 violation_id | target_selector (matches element_selector exactly) | verification_status | retry_count
          778 | tr[height="25px"]:nth-child(2) > ...                | NULL                 | 0
```

**Real rate-limit failure, real proof of "no partial state."** During the
same scan, calling the same violation 778 again hit a genuine 429 on the
Developer node — after Reviewer and Impact had already succeeded in
memory. Direct `psql` query immediately after:
```
 id  | confidence
-----+------------
 778 | (null)

impact_assessments WHERE violation_id=778: (0 rows)
fixes WHERE violation_id=778: (0 rows)
```
Zero rows in both tables despite two of three nodes having succeeded —
the "commit only after full graph success" design held under a real
failure, not a staged one.

**Cache hit, real data.** Same violation, called 3 times:
```
 id | agent_name | latency_ms | tokens_used | cache_hit | confidence_score
  1 | Reviewer   |       4553 |           0 | f         | (failed, transient)
  2 | Reviewer   |       1628 |         678 | f         | 0.95
  3 | Reviewer   |          0 |           0 | t         | 0.95
```

**Mock mode, through the real `/scan` endpoint**, not just in isolation
(`LLM_MOCK=true`, scan_id 11, same W3C page, 43 violations):
```
total violations: 43
with confidence set: 43
with fix set: 43
llm_call_logs rows in that window: 129, all is_mock=true
real Groq calls made: 0
```

**The rate-limit discovery itself**, from Groq's own response headers:
```
x-ratelimit-limit-requests: 1000       (daily)
x-ratelimit-limit-tokens: 6000         (per-minute — the real bottleneck)
x-ratelimit-remaining-tokens: 5616
x-ratelimit-reset-tokens: 3.84s
```
At ~650 tokens/real-call, that's ~9 sustainable calls/minute — not the
~41/minute the original RPM-based planning math predicted. Logged as a
real, measured constraint in design.md Section 7 and PLAN.md's Phase 5
section, not silently absorbed.

**Independent subagent review** (per PLAN.md Phase 2's own verify step):
confirmed exactly 4 `add_node` calls in `graph.py`, linear edges, no
hidden subgraph, clean per-node responsibility boundaries, no unnecessary
abstraction in `llm_client.py`/`agents/`, and an appropriately-scoped
`run_scan` reasoning loop. Full report folded into PLAN.md's session log.

## 8. What was explicitly NOT done in Phase 2 (deferred, not forgotten)

- **No local Ollama anywhere** — abandoned for the reasons in Section 1.
  If a future session wants to revisit local inference, the RAM
  constraint and the real Groq benchmark numbers are the starting point,
  not a fresh guess.
- **No strict/schema-guaranteed structured output.** qwen3-32b doesn't
  support it on Groq. Non-strict `json_object` mode + Pydantic validation
  is the correctness backstop instead — a validation failure is a real,
  expected, fully-handled failure mode (see `error_type=validation_error`),
  not a gap.
- **No caching for Developer or Impact agents** — deferred to Phase 3's
  "real cost optimization" scope (see Section 6's reasoning). Only
  Reviewer is cached in Phase 2.
- **No retry logic for failed LLM calls.** A timeout/429/validation
  failure aborts that violation cleanly and moves on — there is no
  automatic retry-once behavior for reasoning-layer calls in Phase 2
  (CLAUDE.md's retry-once-then-manual_review rule is specifically about
  Phase 3's fix-verification step, not this layer, and wasn't extended
  here without being asked).
- **No real Verifier logic.** The 4th node is a structural stub only —
  `status="pending_verification"`, nothing else. `fixes.verification_status`
  stays `NULL` for every fix Phase 2 produces.
- ~~No rate-limit backoff/pacing~~ — **this was true when Phase 2 first
  shipped, and is no longer true.** The 6,000 TPM ceiling discovered live
  (Section 7) kept biting badly enough on anything past a handful of
  violations that pacing was added as an explicit, separately-approved
  Phase 2 addendum rather than left broken until Phase 3. See Section 11.
- **No frontend work, no dashboard.** Out of scope for Phase 2 per
  PLAN.md's phase ordering (Phase 4).
- **No changes to the crawler or detector.** Phase 1's modules are
  untouched.

## 9. Deviations from the approved plan, and why

1. **Model choice changed twice during planning** (Ollama → generic
   "hosted API" → Cerebras (rejected) → Groq gpt-oss-120b (initially
   favored) → Groq qwen3-32b (final)) before any code was written — all
   before-code decisions, not mid-implementation pivots. Full reasoning
   trail is in the plan file, condensed into design.md Section 7.
2. **Structured-output scope narrowed mid-planning:** the plan originally
   said nodes use structured mode "where the schema allows it"; this was
   tightened to "confirm unconditional" per explicit request, which
   surfaced the gpt-oss-only limitation above — resolved by accepting
   non-strict mode + validation rather than switching models again.
3. **Cache design scope narrowed from "all 3 agents" to "Reviewer only"**
   after identifying the `target_selector` correctness risk for Developer
   caching — confirmed with you before implementation, not discovered
   after the fact.
4. **`error` field cap raised from an initial 2000 chars to 8000** to
   comfortably capture both the Pydantic validation message and a raw
   response snippet, since `max_tokens` (2048) means a fully-wrong
   response could itself run long.
5. **A cosmetic false alarm, caught and ruled out, not silently left
   ambiguous:** an em-dash in a mock string appeared mangled
   (`â€”`) in one terminal-displayed JSON dump during
   testing. Traced through Postgres raw bytes → SQLAlchemy read → raw
   HTTP response bytes — all three showed correct UTF-8 at every stage.
   The corruption was purely a terminal-display artifact in the sandboxed
   shell used for testing, not a real data bug. No code was changed for
   this; documented here so it isn't mistaken for an unresolved issue.

No other deviations. PLAN.md's Phase 2 checkboxes and session log, and
design.md Sections 7-9, reflect everything above.

## 11. Addendum — rate-limit-aware pacing (added after this report was first written)

Not part of the originally approved Phase 2 plan. Added after real
verification (Section 7) showed the 6,000 TPM ceiling turning "occasional
429, cleanly skipped" into "every violation past the first few fails" —
different from Phase 3's planned cost optimization (that's about making
*fewer* calls; this is about not exceeding the rate of calls made), so
fixed now rather than left broken until Phase 3. Went through its own
Plan Mode round and explicit approval before any code was written.

**What was built, entirely inside `backend/app/llm_client.py`** (no
changes to `run_scan` or `graph.py`): module-level state tracking Groq's
real remaining-token budget and reset deadline, read from response
headers after every real call (success or 429 — both carry them); an
`asyncio.Lock` serializing the pace-check + HTTP call + state update as
one atomic unit, since this project already runs concurrent scans via
`BackgroundTasks` and two scans could otherwise race past each other's
view of the shared per-account budget; an adaptive wait that only sleeps
when remaining tokens drop below a safety margin, otherwise proceeding
immediately. Existing per-violation failure handling is unchanged — this
sits in front of it, not in place of it.

**Real, reconciled before/after numbers** — re-ran the exact same
43-violation W3C WAI "bad" demo page scan that was 43/43 failed unpaced:

| | Unpaced (original Phase 2 verification) | Paced |
|---|---|---|
| Violations with confidence | 0/43 | 37/43 (86%) |
| Real calls / failed calls | 43/43 failed almost immediately | 124 total, 118 succeeded, 6 failed |

Every one of the 6 failed calls maps to exactly one of the 6 violations
left without a confidence score — reconfirming "abort on first failure,
no partial state" holds under sustained real load, not just one staged
failure.

**A real mistake, caught before being reported as fact:** the first
before/after comparison used a bare local-looking timestamp
(`'2026-07-06 18:52:00'`) against a `timestamptz` column, which Postgres
read as UTC — four hours off from the scan's actual UTC window, silently
pulling in an entire day's unrelated earlier testing and producing an
inflated, wrong 88-failure count. Caught by cross-checking against the
scan's own `started_at`/`completed_at`, not left in the record.

**One tuning change made from that real data:** `TOKEN_SAFETY_MARGIN`
raised 1000 → 1500 after seeing real Developer calls run up to 1,362
tokens — above the original margin, plausibly explaining part of the
residual 6 failures.

**Re-verified at full scale, closing this item rather than leaving it a
guess:** re-ran the identical 43-violation scan a third time with the new
margin. **129/129 real calls succeeded, 0 failures of any kind, 43/43
violations got full confidence/impact/fix** — up from 118/124 calls (95%)
and 37/43 violations (86%) at the 1,000 margin. The residual failures at
1,000 genuinely were a margin-sizing problem, confirmed with data rather
than assumed fixed.

Full reasoning in design.md Section 8b; session-log entries in PLAN.md.

## 12. Phase 1 + Phase 2 coordination — verified on request, before any commit

Asked directly whether Phase 1 (crawl/detect) and Phase 2 (reason) had
actually been tested together, end to end, with the *current* final code
— not an earlier version. Honest answer at the time: not fully. Two real
gaps existed and were closed before answering further:

1. **Phase 1's own regression sites (example.com, usa.gov) had never been
   re-run against the current code** — they were only ever tested against
   an earlier Phase 2 build, before the pacing addendum existed.
2. **`TOKEN_SAFETY_MARGIN=1500` had only been import-checked**, never
   exercised in an actual scan.

Closed both by re-running scan 13 (`example.com`) and scan 14 (`usa.gov`)
against the current server. `example.com`: identical clean behavior to
every prior run (0 violations, done in ~4.4s). `usa.gov`: 15 pages
crawled correctly (same defensive handling as Phase 1 — no regressions in
`crawler.py`/`detector.py`, confirmed untouched via `git diff --stat`
returning empty), and this crawl's real content happened to surface
**3 real violations** (a different real page than the last usa.gov run —
site navigation/link discovery varies run to run, not a bug).

Of those 3: **1 fully succeeded** end to end (correct not-critical-path
judgment on an analytics sub-page, a real sensible fix wrapping a
malformed `<li>` in a proper `<ul>`). The other 2 failed, for two
*different* real reasons — both caught and handled exactly as designed
(clean abort, zero partial state, correct `error_type`):
- One hit rate-limiting again despite pacing — expected, consistent with
  pacing being "proactive, not a guarantee."
- One surfaced a **new discovery**: Groq's non-strict `json_object` mode
  can hard-reject a generation with a 400 `json_validate_failed` and
  **zero recoverable content** (`failed_generation` came back empty).
  Reproduced directly (identical retry, identical failure) — not
  transient. This corrected a subtly-wrong claim in design.md Section 8b
  (that non-strict mode "guarantees valid JSON syntax" — it doesn't;
  it's "valid JSON, or total rejection with nothing to inspect"). Already
  safely handled as a generic `http_error`; no code change made from only
  2 data points — real per-rule failure-rate data during Phase 5 is the
  actual trigger to investigate further, not a guess now.

**Conclusion: coordination is sound.** Crawl → detect → persist → reason
→ persist-on-success works correctly together across three genuinely
different real sites (example.com, usa.gov, W3C's demo page) at three
different violation scales (0, 3, 43). What is *not* claimed, and never
was: 100% reasoning success per call — Groq itself is imperfect in more
than one way, and this round of testing found a second one.

## 13. What's left running

- `accessibility_agent_postgres` container: up, healthy, port 5433.
- `uvicorn main:app --port 8000`: running in **normal mode**
  (`LLM_MOCK` unset/false), loaded with the pacing code and
  `TOKEN_SAFETY_MARGIN=1500` — safe to leave running or stop.
- 15 scans total in the DB (7 from Phase 1, 8 from this session: 7=
  example.com, 8=usa.gov [0 violations — site content changed since
  Phase 1], 9=W3C demo page [real reasoning data, includes the
  rate-limit-failure proof on violation 778, unpaced], 10=aborted
  mock-mode attempt [port-bind failure, no real data], 11=W3C demo page
  [full mock-mode proof], 12=W3C demo page again [paced verification at
  margin=1000, 37/43 succeeded], 13=example.com regression re-check,
  14=usa.gov regression re-check [3 real violations, 1 succeeded, 2
  failed for two different real reasons — see Section 12], 15=W3C demo
  page a third time [paced verification at margin=1500, 43/43 succeeded,
  0 failures — see Section 11]). Safe to leave or clean up — none are
  load-bearing for future phases.
- 515 `llm_call_logs` rows, 41 `llm_response_cache` rows accumulated
  across this session's testing — real data, not seeded/fake.
- All items from the prior "is this actually done" review are now closed:
  margin=1500 re-verified at full scale (Section 11), Phase 1+2
  coordination re-verified (Section 12), the json_object claim corrected
  (design.md Section 8b). Committed to git next.
