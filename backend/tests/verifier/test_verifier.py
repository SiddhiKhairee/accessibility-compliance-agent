"""
test_verifier.py — Phase 3 regression coverage for verifier.py's
verify_fix() and graph.py's real verifier_node.

Reuses existing, already-hand-verified fixtures from
fixtures/detector_pages/ rather than adding new ones — missing_alt.html
(image-alt, target selector "img") and duplicate_id_aria.html
(duplicate-id-aria, needs_review, target selector "span:nth-child(2)")
cover every outcome this suite needs. Every outerHTML-replacement fix
below was run live against the real detector this session before being
trusted here (not guessed) — see the inline notes on each fixture's real
before/after selector output.

Deliberately not a pytest fixture for Playwright lifecycle, same
documented reason as test_detector.py: launching Playwright inside an
async-generator fixture reliably hangs in this environment. Every test
here inlines its own start()/launch()/...</stop() sequence directly.
"""
from playwright.async_api import Locator, async_playwright

import verifier
from graph import verifier_node
from models import FixFailureReason, FixVerificationStatus


async def test_verify_fix_verified_clean(test_server):
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page_url = f"{test_server.base_url}/detector_pages/missing_alt.html"
            result = await verifier.verify_fix(
                page_url=page_url,
                original_wcag_rule="image-alt",
                original_element_selector="img",
                target_selector="img",
                proposed_code_diff='<img src="x.jpg" alt="Hero image">',
                baseline=[{"wcag_rule": "image-alt", "element_selector": "img"}],
            )
            assert result.outcome == "verified"
            assert result.failure_reason is None
        finally:
            await browser.close()
    finally:
        await playwright.stop()


async def test_verify_fix_rejected_violation_persists(test_server):
    """Confirmed live: adding a non-accessible-name attribute (data-foo)
    leaves image-alt failing exactly as before — data-foo has no bearing
    on axe's accessible-name computation, unlike e.g. `title`, which this
    session confirmed DOES satisfy image-alt (an axe accepted-fallback,
    not a bug in verify_fix) and was rejected as this fixture's "broken
    fix" for that reason."""
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page_url = f"{test_server.base_url}/detector_pages/missing_alt.html"
            result = await verifier.verify_fix(
                page_url=page_url,
                original_wcag_rule="image-alt",
                original_element_selector="img",
                target_selector="img",
                proposed_code_diff='<img src="x.jpg" data-foo="bar">',
                baseline=[{"wcag_rule": "image-alt", "element_selector": "img"}],
            )
            assert result.outcome == "violation_persists"
        finally:
            await browser.close()
    finally:
        await playwright.stop()


async def test_verify_fix_rejected_new_violation(test_server):
    """The proposed fix resolves the original image-alt violation but
    replaces the single <img> with a <div> wrapping the fixed image plus a
    new unlabeled <input> — confirmed live to produce exactly one new
    ('label', '#newinput') violation not present in the baseline."""
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page_url = f"{test_server.base_url}/detector_pages/missing_alt.html"
            result = await verifier.verify_fix(
                page_url=page_url,
                original_wcag_rule="image-alt",
                original_element_selector="img",
                target_selector="img",
                proposed_code_diff=(
                    '<div><img src="x.jpg" alt="Hero image">'
                    '<input id="newinput"></div>'
                ),
                baseline=[{"wcag_rule": "image-alt", "element_selector": "img"}],
            )
            assert result.outcome == "new_violation"
        finally:
            await browser.close()
    finally:
        await playwright.stop()


async def test_verify_fix_dom_changed_selector_not_found(test_server):
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page_url = f"{test_server.base_url}/detector_pages/missing_alt.html"
            result = await verifier.verify_fix(
                page_url=page_url,
                original_wcag_rule="image-alt",
                original_element_selector="img",
                target_selector="#does-not-exist",
                proposed_code_diff='<img src="x.jpg" alt="Hero image">',
                baseline=[{"wcag_rule": "image-alt", "element_selector": "img"}],
            )
            assert result.outcome == "error"
            assert result.failure_reason == "dom_changed"
        finally:
            await browser.close()
    finally:
        await playwright.stop()


async def test_verify_fix_invalid_html_caught_pre_playwright():
    """No page_url needs to resolve at all — the structural sanity check
    runs before any Playwright work, so a deliberately truncated/unbalanced
    snippet is caught immediately."""
    result = await verifier.verify_fix(
        page_url="http://127.0.0.1:1/never-fetched",
        original_wcag_rule="image-alt",
        original_element_selector="img",
        target_selector="img",
        proposed_code_diff='<img src="x.jpg" alt="Hero',  # truncated, unbalanced
        baseline=[{"wcag_rule": "image-alt", "element_selector": "img"}],
    )
    assert result.outcome == "error"
    assert result.failure_reason == "invalid_html"


async def test_verify_fix_playwright_timeout(test_server, monkeypatch):
    """Reuses fixtures/server.py's existing /slow endpoint (sleeps
    SLOW_DELAY_S=3.0s) with PAGE_LOAD_TIMEOUT_MS monkeypatched small so the
    navigation deterministically times out fast."""
    monkeypatch.setattr(verifier, "PAGE_LOAD_TIMEOUT_MS", 200)
    result = await verifier.verify_fix(
        page_url=f"{test_server.base_url}/slow",
        original_wcag_rule="image-alt",
        original_element_selector="img",
        target_selector="img",
        proposed_code_diff='<img src="x.jpg" alt="Hero image">',
        baseline=[{"wcag_rule": "image-alt", "element_selector": "img"}],
    )
    assert result.outcome == "error"
    assert result.failure_reason == "playwright_timeout"


async def test_verify_fix_diff_failed_to_apply(test_server, monkeypatch):
    """Real browsers are extremely forgiving of outerHTML assignment, so
    there's no realistic HTML fixture that makes Locator.evaluate() throw
    organically — monkeypatch it to raise directly instead."""
    async def _raise(*args, **kwargs):
        raise RuntimeError("simulated evaluate failure")

    monkeypatch.setattr(Locator, "evaluate", _raise)
    result = await verifier.verify_fix(
        page_url=f"{test_server.base_url}/detector_pages/missing_alt.html",
        original_wcag_rule="image-alt",
        original_element_selector="img",
        target_selector="img",
        proposed_code_diff='<img src="x.jpg" alt="Hero image">',
        baseline=[{"wcag_rule": "image-alt", "element_selector": "img"}],
    )
    assert result.outcome == "error"
    assert result.failure_reason == "diff_failed_to_apply"


async def test_verify_fix_needs_review_baseline_diffs_like_confirmed(test_server):
    """duplicate_id_aria.html's violation is detection_confidence
    "needs_review" (Phase 2.6's reviewOnFail gap), not "confirmed" — the
    baseline dict verify_fix() receives carries no detection_confidence at
    all (just wcag_rule/element_selector), so this proves the diff logic
    treats a needs_review entry identically to a confirmed one for
    identity purposes. Confirmed live: renaming the duplicated id resolves
    the violation with no new violation introduced."""
    result = await verifier.verify_fix(
        page_url=f"{test_server.base_url}/detector_pages/duplicate_id_aria.html",
        original_wcag_rule="duplicate-id-aria",
        original_element_selector="span:nth-child(2)",
        target_selector="span:nth-child(2)",
        proposed_code_diff='<span id="dup2">Duplicate id</span>',
        baseline=[{"wcag_rule": "duplicate-id-aria", "element_selector": "span:nth-child(2)"}],
    )
    assert result.outcome == "verified"


async def test_verifier_node_retry_count_increments_on_first_failure(test_server, monkeypatch):
    """Mechanical retry only: monkeypatch graph.verify_fix to fail once
    then succeed, and confirm the graph-level VerifierOutput reports
    retry_count == 1 with the retry's own (successful) outcome winning."""
    import graph as graph_module

    calls = {"n": 0}

    async def _fake_verify_fix(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return verifier.VerifyAttemptResult(outcome="error", failure_reason="playwright_timeout")
        return verifier.VerifyAttemptResult(outcome="verified")

    monkeypatch.setattr(graph_module, "verify_fix", _fake_verify_fix)

    from agents.developer.schema import DeveloperOutput

    state = {
        "violation": {
            "id": 1,
            "wcag_rule": "image-alt",
            "element_selector": "img",
            "html_snippet": '<img src="x.jpg">',
            "message": "missing alt",
            "page_url": f"{test_server.base_url}/detector_pages/missing_alt.html",
        },
        "baseline_violations": [{"wcag_rule": "image-alt", "element_selector": "img"}],
        "developer_result": DeveloperOutput(
            proposed_code_diff='<img src="x.jpg" alt="Hero image">',
            target_selector="img",
        ),
    }
    result = await verifier_node(state)
    assert calls["n"] == 2
    assert result["verifier_result"].verification_status == FixVerificationStatus.verified
    assert result["verifier_result"].retry_count == 1
    assert result["verifier_result"].failure_reason is None


async def test_verifier_node_manual_review_when_retry_also_fails(test_server, monkeypatch):
    import graph as graph_module

    async def _always_fail(**kwargs):
        return verifier.VerifyAttemptResult(outcome="error", failure_reason="dom_changed")

    monkeypatch.setattr(graph_module, "verify_fix", _always_fail)

    from agents.developer.schema import DeveloperOutput

    state = {
        "violation": {
            "id": 2,
            "wcag_rule": "image-alt",
            "element_selector": "img",
            "html_snippet": '<img src="x.jpg">',
            "message": "missing alt",
            "page_url": f"{test_server.base_url}/detector_pages/missing_alt.html",
        },
        "baseline_violations": [{"wcag_rule": "image-alt", "element_selector": "img"}],
        "developer_result": DeveloperOutput(
            proposed_code_diff='<img src="x.jpg" alt="Hero image">',
            target_selector="img",
        ),
    }
    result = await verifier_node(state)
    assert result["verifier_result"].verification_status == FixVerificationStatus.manual_review
    assert result["verifier_result"].failure_reason == FixFailureReason.dom_changed
    assert result["verifier_result"].retry_count == 1
