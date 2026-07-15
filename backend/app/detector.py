"""
detector.py — axe-core WCAG violation detector.

Given an already-loaded Playwright page (loaded by crawler.py), runs
axe-core restricted to the locked v1 rule set (design.md Section 2 /
PLAN.md Phase 0) and returns structured violation data — not a report
string — so callers can persist directly to the `violations` table
(docs/schema.md).
"""
import asyncio
import sys
from dataclasses import dataclass

from axe_playwright_python.async_playwright import Axe
from playwright.async_api import Page, async_playwright

# Locked v1 WCAG rule set (design.md Section 2 / PLAN.md Phase 0) — the 9
# rules fully automatable via axe-core, no manual-judgment rules. Passed
# via axe's own `runOnly` option so axe-core never evaluates anything
# outside this set, rather than evaluating everything and filtering after
# the fact (verified against 7 real sites — see design.md Section 4c).
LOCKED_RULE_IDS = [
    "image-alt", "input-image-alt",       # 1. Non-text Content (1.1.1)
    "color-contrast",                      # 2. Contrast Minimum (1.4.3)
    "label", "button-name", "aria-input-field-name",  # 3. Name/Role/Value (4.1.2)
    "tabindex",                            # 4. Keyboard (2.1.1)
    "html-has-lang", "html-lang-valid",    # 5. Language of Page (3.1.1)
    "bypass", "skip-link",                 # 6. Bypass Blocks (2.4.1)
    "duplicate-id-aria",                   # 7. Duplicate ARIA/label IDs (4.1.2)
    "list", "listitem", "definition-list", # 8. Info and Relationships (1.3.1)
    "link-name",                           # 9. Link Purpose (2.4.4)
]

# Rules whose genuine failures can land in axe's `incomplete` result array
# instead of `violations` — without this list, detect_violations() (which
# only reads `violations` for everything else) would silently miss those
# failures. Two different mechanisms feed this list, not one:
#
# - `bypass`, `duplicate-id-aria`: axe-core marks both `reviewOnFail: true`
#   in its own rule metadata (confirmed live, Phase 2.5/2.6: loaded the real
#   bundled axe.min.js in a headless Chromium page and queried
#   `axe._audit.rules` directly for all 16 locked rule IDs — see design.md
#   Section 3). Metadata predicts these rules *always* need human judgment
#   on a genuine fail, so they always land in `incomplete`.
# - `color-contrast`: NOT tagged `reviewOnFail` — added based on direct
#   runtime evidence, not metadata (Phase 2.6 Part 1 audit). A real page
#   (target.com, Pass 1a crawl) and a constructed fixture
#   (color_contrast_ambiguous.html — a background-image case, distinct from
#   color_contrast.html's flat low-contrast case) both showed a genuine
#   color-contrast failure landing in `incomplete`, with no metadata flag
#   predicting it. Metadata predicts "this rule always needs human
#   judgment"; it does NOT predict "this rule's automated check can become
#   ambiguous on some pages" — those are different mechanisms, and this
#   list is now maintained against both, not metadata alone.
#
# The other 13 locked rule IDs were each confirmed safe (genuine failure
# lands in `violations`) against exactly ONE real-failure fixture apiece —
# see design.md Section 3 for the full audit table. That reduces risk, it
# does not prove no other page construction could ever push one of those
# 13 into `incomplete` too. If evaluation data ever looks anomalously
# sparse for a specific locked rule (e.g. a rule that should appear often
# across the eval corpus showing suspiciously few hits), treat that as a
# signal worth re-auditing that rule, not something to dismiss.
#
# Hardcoded rather than re-queried/re-audited at runtime, same rationale as
# LOCKED_RULE_IDS: verified once, deterministic, no runtime cost.
REVIEW_ON_FAIL_RULE_IDS = ["bypass", "duplicate-id-aria", "color-contrast"]

AXE_OPTIONS = {
    "resultTypes": ["violations", "incomplete"],
    "runOnly": {"type": "rule", "values": LOCKED_RULE_IDS},
}


@dataclass
class Violation:
    wcag_rule: str
    element_selector: str
    severity: str  # axe "impact": minor / moderate / serious / critical
    html_snippet: str
    message: str
    # "confirmed" (axe reached a definitive fail) or "needs_review" (pulled
    # from axe's `incomplete` array for a REVIEW_ON_FAIL_RULE_IDS rule —
    # axe itself wasn't fully confident). Defaults to "confirmed" so every
    # existing call site is unaffected. See design.md Section 3: this phase
    # only surfaces/persists needs_review violations, it does not change
    # how downstream agent nodes treat them.
    detection_confidence: str = "confirmed"
    # No `confidence` field here on purpose — axe-core has no equivalent
    # signal to offer. That's the Reviewer Agent's job (Phase 2), not
    # something to fake here.


async def detect_violations(page: Page) -> list[Violation]:
    """Run the locked v1 rule set against an already-loaded page.

    One Violation per (rule, element) pair — a rule with 3 offending
    elements on the page produces 3 Violations, matching the one-row-per-
    element shape of the `violations` table.
    """
    results = await Axe().run(page, options=AXE_OPTIONS)

    violations: list[Violation] = []
    for v in results.response["violations"]:
        for node in v["nodes"]:
            checks = node.get("all", []) + node.get("any", []) + node.get("none", [])
            violations.append(Violation(
                wcag_rule=v["id"],
                element_selector=", ".join(node["target"]),
                severity=v["impact"] or "unknown",
                html_snippet=node.get("html", ""),
                message="; ".join(c["message"] for c in checks),
            ))

    for v in results.response["incomplete"]:
        if v["id"] not in REVIEW_ON_FAIL_RULE_IDS:
            continue
        for node in v["nodes"]:
            checks = node.get("all", []) + node.get("any", []) + node.get("none", [])
            violations.append(Violation(
                wcag_rule=v["id"],
                element_selector=", ".join(node["target"]),
                severity=v["impact"] or "unknown",
                html_snippet=node.get("html", ""),
                message="; ".join(c["message"] for c in checks),
                detection_confidence="needs_review",
            ))

    return violations


async def _main(url: str) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            # networkidle waits for JS-rendered content to settle, since
            # accessibility violations often live there and we need the
            # fully-rendered DOM. Slower than "load"/"domcontentloaded" —
            # Step 4 adds a faster fallback strategy for pages that never
            # go idle.
            await page.goto(url, wait_until="networkidle", timeout=10000)

            violations = await detect_violations(page)
            print(f"Violations found: {len(violations)}")
            for v in violations:
                print(f"- [{v.severity}] {v.wcag_rule} @ {v.element_selector}")
                print(f"  {v.message}")
        except Exception as e:
            print(f"Failed to scan {url}: {e}")
        finally:
            await browser.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python detector.py <url>")
        sys.exit(1)

    asyncio.run(_main(sys.argv[1]))
