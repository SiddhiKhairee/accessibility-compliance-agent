"""
verifier.py — Phase 3 apply-fix-and-reverify logic. Given a violation's
proposed fix, loads the live page fresh, replaces the target element's
outerHTML, reruns detect_violations(), and diffs the after-set against the
page's pre-fix baseline. Same flat-module, own-Playwright-lifecycle
convention as detector.py/crawler.py — no DB access here at all (graph.py's
verifier_node passes in plain data and stays a pure function per its own
module docstring; main.py's run_scan threads the baseline in, this module
never queries it).

verify_fix() never raises — every failure mode is caught internally and
mapped to a VerifyAttemptResult(outcome="error", failure_reason=...), so
graph.py's mechanical retry loop never needs its own try/except around this
call.
"""
import asyncio
import html.parser
import logging
from dataclasses import dataclass

from playwright.async_api import async_playwright

from detector import detect_violations

logger = logging.getLogger("accessibility_agent.verifier")

# Matches crawler.py's PAGE_LOAD_TIMEOUT_MS / DETECTION_TIMEOUT_S conventions.
PAGE_LOAD_TIMEOUT_MS = 10000
DETECTION_TIMEOUT_S = 10
# New — bounds the outerHTML-replacement evaluate() call specifically.
APPLY_TIMEOUT_S = 5

_VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


@dataclass
class VerifyAttemptResult:
    outcome: str  # "verified" | "violation_persists" | "new_violation" | "error"
    # A FixFailureReason.value string, only set when outcome == "error".
    failure_reason: str | None = None
    detail: str = ""


class _TagBalanceChecker(html.parser.HTMLParser):
    """Best-effort structural sanity check only — stdlib html.parser (and
    real browsers) are extremely lenient and essentially never "reject"
    malformed HTML the way an XML parser would. This can only catch gross
    structural breakage (unclosed tags, a stray closing tag with no
    matching open) — most plausibly caused by a truncated LLM response
    (see llm_client.py's MAX_TOKENS docstring) — not most things a human
    would call "invalid" HTML. A partial, not complete, invalid_html check;
    no HTML validation library is in requirements.txt and none is being
    added just for this.
    """

    def __init__(self):
        super().__init__()
        self.stack: list[str] = []
        self.saw_any_tag = False
        self.mismatched = False

    def handle_starttag(self, tag, attrs):
        self.saw_any_tag = True
        if tag not in _VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.saw_any_tag = True  # self-closing, e.g. <img ... />

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass
        elif tag not in _VOID_ELEMENTS:
            self.mismatched = True


def _looks_like_invalid_html(snippet: str) -> bool:
    stripped = snippet.strip()
    if not stripped:
        return True
    checker = _TagBalanceChecker()
    try:
        checker.feed(stripped)
    except Exception:
        return True
    if not checker.saw_any_tag:
        return True
    if checker.mismatched:
        return True
    if checker.stack:  # unclosed tags remaining
        return True
    return False


async def verify_fix(
    page_url: str,
    original_wcag_rule: str,
    original_element_selector: str,
    target_selector: str,
    proposed_code_diff: str,
    baseline: list[dict],
) -> VerifyAttemptResult:
    """Single attempt (no retry loop here — that's graph.py's job, since
    retry-vs-not is a node-orchestration decision, not a Playwright-
    lifecycle one). `baseline` is [{"wcag_rule": ..., "element_selector":
    ...}, ...] for every violation detected on this page before any fix was
    applied — supplied by the caller, never queried here.
    """
    if _looks_like_invalid_html(proposed_code_diff):
        return VerifyAttemptResult(
            outcome="error", failure_reason="invalid_html",
            detail="proposed_code_diff failed pre-apply structural sanity check",
        )

    playwright = None
    browser = None
    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(page_url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT_MS)
        except Exception as e:
            return VerifyAttemptResult(
                outcome="error", failure_reason="playwright_timeout",
                detail=f"page load failed: {e}",
            )

        locator = page.locator(target_selector)
        try:
            count = await locator.count()
        except Exception as e:
            return VerifyAttemptResult(
                outcome="error", failure_reason="dom_changed",
                detail=f"target_selector did not resolve as a valid locator: {e}",
            )
        if count == 0:
            return VerifyAttemptResult(
                outcome="error", failure_reason="dom_changed",
                detail="target_selector matched zero elements (DOM changed since Developer ran)",
            )
        if count > 1:
            return VerifyAttemptResult(
                outcome="error", failure_reason="dom_changed",
                detail=f"target_selector ambiguously matched {count} elements",
            )

        try:
            await asyncio.wait_for(
                locator.evaluate("(el, html) => { el.outerHTML = html; }", proposed_code_diff),
                timeout=APPLY_TIMEOUT_S,
            )
        except Exception as e:
            return VerifyAttemptResult(
                outcome="error", failure_reason="diff_failed_to_apply",
                detail=f"outerHTML replacement failed: {e}",
            )

        try:
            after = await asyncio.wait_for(detect_violations(page), timeout=DETECTION_TIMEOUT_S)
        except Exception as e:
            return VerifyAttemptResult(
                outcome="error", failure_reason="playwright_timeout",
                detail=f"post-fix detect_violations rerun failed/hung: {e}",
            )

        after_pairs = {(v.wcag_rule, v.element_selector) for v in after}
        baseline_pairs = {(b["wcag_rule"], b["element_selector"]) for b in baseline}
        original_pair = (original_wcag_rule, original_element_selector)

        original_gone = original_pair not in after_pairs
        new_violations = after_pairs - baseline_pairs - {original_pair}

        if original_gone and not new_violations:
            return VerifyAttemptResult(outcome="verified", detail="original gone, no new violations")
        if not original_gone:
            return VerifyAttemptResult(
                outcome="violation_persists",
                detail=f"{original_pair} still present in after-set",
            )
        return VerifyAttemptResult(
            outcome="new_violation",
            detail=f"original gone but new violation(s) appeared: {sorted(new_violations)}",
        )

    except Exception as e:
        # Catch-all for anything not classified above — never silently drop
        # it per CLAUDE.md; log the full traceback, map to the broadest
        # bucket.
        logger.exception("verify_fix: unclassified failure for %s", page_url)
        return VerifyAttemptResult(
            outcome="error", failure_reason="diff_failed_to_apply",
            detail=f"unclassified failure: {e}",
        )
    finally:
        if browser is not None:
            await browser.close()
        if playwright is not None:
            await playwright.stop()
