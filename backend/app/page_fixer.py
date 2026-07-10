"""
page_fixer.py — Phase 4 combine-and-reverify. Given a page's already-
approved, individually-verified fixes, applies all of them onto one copy of
the page and reruns the full detector once on the combined result.

Same flat-module, own-Playwright-lifecycle convention as
crawler.py/detector.py/verifier.py — no DB access here at all (main.py's
POST /pages/{id}/generate-fixed-page endpoint queries the DB, builds the
inputs below, and persists the result; this module stays a pure function).

Deliberately applies fixes to the page's already-captured
`raw_html_snapshot_path` content (via `page.set_content()`) rather than a
fresh `page.goto(page_url)` reload. Verification happens at scan time, but
human approval — and therefore this combine step — can happen minutes,
hours, or days later; reloading the live site at that point could silently
apply the combined fix to different content than what was actually
verified. Anchoring to the snapshot instead guarantees "what was verified"
and "what gets combined" are the same content. This does not guarantee
byte-identical content to whatever each fix's own verify_fix() call saw
during its live reload (a smaller, pre-existing Phase 3 imprecision — see
design.md's Phase 4 section) — it only closes the much larger gap Phase 4's
human-approval delay would otherwise introduce.

A `<base href="{page_url}">` tag is injected into the snapshot before
`set_content()` so relative CSS/JS/image references still resolve against
the real origin — needed both for accurate rendering during the combined
detector rerun (e.g. color-contrast depends on computed styles actually
loading) and, since it ends up in the final `page.content()` output, for
the downloaded fixed-page artifact too. One injection serves both needs.

apply_verified_fixes_to_page() never raises — every failure mode is caught
internally and mapped to a CombinedFixResult(status="error", ...), matching
verifier.py's verify_fix() convention.
"""
import asyncio
import html as html_module
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import async_playwright

from detector import detect_violations
from verifier import apply_fix_to_locator

logger = logging.getLogger("accessibility_agent.page_fixer")

# Matches verifier.py's PAGE_LOAD_TIMEOUT_MS/DETECTION_TIMEOUT_S conventions.
PAGE_LOAD_TIMEOUT_MS = 10000
DETECTION_TIMEOUT_S = 10

_HEAD_OPEN_RE = re.compile(r"<head[^>]*>", re.IGNORECASE)


@dataclass
class FixToApply:
    wcag_rule: str
    element_selector: str
    target_selector: str
    proposed_code_diff: str


@dataclass
class CombinedFixResult:
    status: str  # "clean" | "violations_remain" | "error"
    detail: str
    fixed_html: str | None = None  # only set on "clean"
    # A FixFailureReason.value string, only set when status == "error" and
    # the failure is one verifier.py's existing vocabulary already covers —
    # some page_fixer-specific error paths (e.g. an unreadable snapshot
    # file) have no matching FixFailureReason and leave this None.
    failure_reason: str | None = None


def _inject_base_href(html_content: str, page_url: str) -> str:
    base_tag = f'<base href="{html_module.escape(page_url, quote=True)}">'
    match = _HEAD_OPEN_RE.search(html_content)
    if match:
        insert_at = match.end()
        return html_content[:insert_at] + base_tag + html_content[insert_at:]
    # No <head> tag at all (malformed/minimal snapshot) — prepend so the
    # <base> still applies to the whole document rather than dropping it.
    return base_tag + html_content


async def apply_verified_fixes_to_page(
    page_url: str,
    raw_html_snapshot_path: str | None,
    fixes: list[FixToApply],
    baseline: list[dict],
) -> CombinedFixResult:
    """`baseline` is [{"wcag_rule": ..., "element_selector": ...}, ...] for
    every violation originally detected on this page (the full pre-fix set,
    not just the ones being fixed here) — same shape verifier.py's
    verify_fix() already takes, supplied by the caller, never queried here.

    "clean" requires both: every fix's own (wcag_rule, element_selector)
    pair is gone from the post-combine detector rerun, AND nothing appears
    that wasn't already in `baseline` — a pre-existing violation that
    simply wasn't approved (not in `fixes`) is expected to still be present
    and is not treated as a failure; only fixes that were attempted but
    didn't take, or genuinely new violations the combination introduced,
    count as "violations_remain".

    Does not know about "how many fixes exist on this page in total" —
    partial-approval accounting (e.g. "3/5 approved") is the caller's
    (main.py's) job, composed into the persisted
    Page.combined_verification_detail alongside this function's own detail.
    """
    if not fixes:
        return CombinedFixResult(status="error", detail="no fixes given to apply")

    # Explicit check, not just relying on Path()/read_text() to raise
    # something catchable: raw_html_snapshot_path is nullable on Page (a
    # Phase 1 decision — see docs/schema.md, only set for status="loaded"
    # pages) and Path(None) raises TypeError, not OSError, which the
    # except clause below does not catch. main.py's caller already guards
    # against this before ever calling in, but this function's own
    # contract ("never raises") should hold regardless of the caller.
    if not raw_html_snapshot_path:
        return CombinedFixResult(
            status="error", detail="raw_html_snapshot_path is missing (page has no captured snapshot)",
        )

    try:
        snapshot_html = Path(raw_html_snapshot_path).read_text(encoding="utf-8")
    except OSError as e:
        return CombinedFixResult(
            status="error", detail=f"could not read raw_html_snapshot_path: {e}",
        )

    html_with_base = _inject_base_href(snapshot_html, page_url)

    playwright = None
    browser = None
    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.set_content(
                html_with_base, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT_MS,
            )
        except Exception as e:
            return CombinedFixResult(
                status="error", detail=f"set_content failed: {e}",
                failure_reason="playwright_timeout",
            )

        applied_pairs: set[tuple[str, str]] = set()
        for fix in fixes:
            locator = page.locator(fix.target_selector)
            try:
                count = await locator.count()
            except Exception as e:
                return CombinedFixResult(
                    status="error",
                    detail=f"target_selector {fix.target_selector!r} for "
                           f"{fix.wcag_rule} did not resolve as a valid locator: {e}",
                    failure_reason="dom_changed",
                )
            if count != 1:
                return CombinedFixResult(
                    status="error",
                    detail=f"target_selector {fix.target_selector!r} for "
                           f"{fix.wcag_rule} matched {count} elements",
                    failure_reason="dom_changed",
                )
            try:
                await apply_fix_to_locator(locator, fix.wcag_rule, fix.proposed_code_diff)
            except Exception as e:
                return CombinedFixResult(
                    status="error",
                    detail=f"applying fix for {fix.wcag_rule} @ "
                           f"{fix.target_selector!r} failed: {e}",
                    failure_reason="diff_failed_to_apply",
                )
            applied_pairs.add((fix.wcag_rule, fix.element_selector))

        try:
            after = await asyncio.wait_for(detect_violations(page), timeout=DETECTION_TIMEOUT_S)
        except Exception as e:
            return CombinedFixResult(
                status="error",
                detail=f"post-fix detect_violations rerun failed/hung: {e}",
                failure_reason="playwright_timeout",
            )

        after_pairs = {(v.wcag_rule, v.element_selector) for v in after}
        baseline_pairs = {(b["wcag_rule"], b["element_selector"]) for b in baseline}

        still_broken = applied_pairs & after_pairs
        new_violations = after_pairs - baseline_pairs

        if still_broken or new_violations:
            parts = []
            if still_broken:
                parts.append(f"still present: {sorted(still_broken)}")
            if new_violations:
                parts.append(f"new violations: {sorted(new_violations)}")
            return CombinedFixResult(status="violations_remain", detail="; ".join(parts))

        fixed_html = await page.content()
        return CombinedFixResult(
            status="clean",
            detail=f"{len(fixes)} fix(es) applied cleanly, no violations remain",
            fixed_html=fixed_html,
        )

    except Exception as e:
        # Catch-all for anything not classified above — never silently drop
        # it per CLAUDE.md; log the full traceback, map to the broadest
        # bucket.
        logger.exception("apply_verified_fixes_to_page: unclassified failure for %s", page_url)
        return CombinedFixResult(status="error", detail=f"unclassified failure: {e}")
    finally:
        if browser is not None:
            await browser.close()
        if playwright is not None:
            await playwright.stop()
