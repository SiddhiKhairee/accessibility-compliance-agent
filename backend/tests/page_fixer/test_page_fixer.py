"""
test_page_fixer.py — Phase 4 regression coverage for page_fixer.py's
apply_verified_fixes_to_page().

Reuses existing hand-verified fixtures where possible (multi_violation.html:
image-alt + tabindex, confirmed live this session — see inline notes) plus
one new fixture, lang_and_alt_violation.html (html-has-lang + image-alt),
added specifically because no existing fixture combines a LANG_RULE_IDS
violation with an unrelated one on the same page — the exact scenario
verifier.py's lang-attribute hardening (see test_verifier.py) was built to
make safe when multiple fixes are combined together, not just applied in
isolation.

Deliberately not a pytest fixture for Playwright lifecycle — same
documented reason as test_detector.py/test_verifier.py (launching
Playwright inside an async-generator fixture reliably hangs in this
environment).
"""
import page_fixer
from fixtures.server import FIXTURES_DIR

DETECTOR_PAGES = FIXTURES_DIR / "detector_pages"


async def test_combines_two_independent_fixes_clean(test_server):
    """multi_violation.html: image-alt (img) + tabindex (div) — confirmed
    live this session to be exactly these two, no noise. Both fixes applied
    together, one combined detector rerun, both gone."""
    snapshot_path = DETECTOR_PAGES / "multi_violation.html"
    fixes = [
        page_fixer.FixToApply(
            wcag_rule="image-alt", element_selector="img",
            target_selector="img", proposed_code_diff='<img src="x.jpg" alt="Hero image">',
        ),
        page_fixer.FixToApply(
            wcag_rule="tabindex", element_selector="div",
            target_selector="div", proposed_code_diff='<div tabindex="0">Focusable div</div>',
        ),
    ]
    baseline = [
        {"wcag_rule": "image-alt", "element_selector": "img"},
        {"wcag_rule": "tabindex", "element_selector": "div"},
    ]
    result = await page_fixer.apply_verified_fixes_to_page(
        page_url=f"{test_server.base_url}/detector_pages/multi_violation.html",
        raw_html_snapshot_path=str(snapshot_path),
        fixes=fixes,
        baseline=baseline,
    )
    assert result.status == "clean"
    assert result.fixed_html is not None
    assert 'alt="Hero image"' in result.fixed_html


async def test_combines_lang_fix_with_unrelated_fix_clean(test_server):
    """The scenario verifier.py's LANG_RULE_IDS hardening exists for:
    html-has-lang (targets the whole <html> element) combined with an
    unrelated image-alt fix on the same page. Before the hardening, a
    full-outerHTML html-has-lang fix applied alongside this would have
    silently overwritten the image-alt fix (or vice versa, depending on
    order) — proving both apply cleanly together is the actual regression
    test for that design decision, not just each one in isolation
    (test_verifier.py already covers isolation)."""
    snapshot_path = DETECTOR_PAGES / "lang_and_alt_violation.html"
    fixes = [
        page_fixer.FixToApply(
            wcag_rule="html-has-lang", element_selector="html",
            target_selector="html", proposed_code_diff="en",
        ),
        page_fixer.FixToApply(
            wcag_rule="image-alt", element_selector="img",
            target_selector="img", proposed_code_diff='<img src="x.jpg" alt="Hero image">',
        ),
    ]
    baseline = [
        {"wcag_rule": "html-has-lang", "element_selector": "html"},
        {"wcag_rule": "image-alt", "element_selector": "img"},
    ]
    result = await page_fixer.apply_verified_fixes_to_page(
        page_url=f"{test_server.base_url}/detector_pages/lang_and_alt_violation.html",
        raw_html_snapshot_path=str(snapshot_path),
        fixes=fixes,
        baseline=baseline,
    )
    assert result.status == "clean"
    assert 'lang="en"' in result.fixed_html
    assert 'alt="Hero image"' in result.fixed_html


async def test_partial_fix_set_leaves_unapproved_violation_untouched(test_server):
    """Only image-alt is approved/fixed; tabindex is deliberately left out
    (simulating a partial-approval page). "clean" should still hold — an
    unapproved pre-existing violation is expected to remain and is not a
    failure, only fixes that were attempted-but-failed or genuinely new
    violations count against "clean"."""
    snapshot_path = DETECTOR_PAGES / "multi_violation.html"
    fixes = [
        page_fixer.FixToApply(
            wcag_rule="image-alt", element_selector="img",
            target_selector="img", proposed_code_diff='<img src="x.jpg" alt="Hero image">',
        ),
    ]
    baseline = [
        {"wcag_rule": "image-alt", "element_selector": "img"},
        {"wcag_rule": "tabindex", "element_selector": "div"},
    ]
    result = await page_fixer.apply_verified_fixes_to_page(
        page_url=f"{test_server.base_url}/detector_pages/multi_violation.html",
        raw_html_snapshot_path=str(snapshot_path),
        fixes=fixes,
        baseline=baseline,
    )
    assert result.status == "clean"


async def test_still_broken_fix_reports_violations_remain(test_server):
    """Same "broken fix" shape as test_verifier.py's
    test_verify_fix_rejected_violation_persists — data-foo has no bearing
    on axe's accessible-name computation, so image-alt still fails."""
    snapshot_path = DETECTOR_PAGES / "multi_violation.html"
    fixes = [
        page_fixer.FixToApply(
            wcag_rule="image-alt", element_selector="img",
            target_selector="img", proposed_code_diff='<img src="x.jpg" data-foo="bar">',
        ),
        page_fixer.FixToApply(
            wcag_rule="tabindex", element_selector="div",
            target_selector="div", proposed_code_diff='<div tabindex="0">Focusable div</div>',
        ),
    ]
    baseline = [
        {"wcag_rule": "image-alt", "element_selector": "img"},
        {"wcag_rule": "tabindex", "element_selector": "div"},
    ]
    result = await page_fixer.apply_verified_fixes_to_page(
        page_url=f"{test_server.base_url}/detector_pages/multi_violation.html",
        raw_html_snapshot_path=str(snapshot_path),
        fixes=fixes,
        baseline=baseline,
    )
    assert result.status == "violations_remain"
    assert "image-alt" in result.detail


async def test_dom_changed_target_selector_missing(test_server):
    snapshot_path = DETECTOR_PAGES / "multi_violation.html"
    fixes = [
        page_fixer.FixToApply(
            wcag_rule="image-alt", element_selector="img",
            target_selector="#does-not-exist", proposed_code_diff='<img src="x.jpg" alt="Hero image">',
        ),
    ]
    baseline = [{"wcag_rule": "image-alt", "element_selector": "img"}]
    result = await page_fixer.apply_verified_fixes_to_page(
        page_url=f"{test_server.base_url}/detector_pages/multi_violation.html",
        raw_html_snapshot_path=str(snapshot_path),
        fixes=fixes,
        baseline=baseline,
    )
    assert result.status == "error"
    assert result.failure_reason == "dom_changed"


async def test_unreadable_snapshot_path_is_error(tmp_path):
    result = await page_fixer.apply_verified_fixes_to_page(
        page_url="http://example.invalid/never-fetched",
        raw_html_snapshot_path=str(tmp_path / "does_not_exist.html"),
        fixes=[
            page_fixer.FixToApply(
                wcag_rule="image-alt", element_selector="img",
                target_selector="img", proposed_code_diff='<img alt="x">',
            ),
        ],
        baseline=[{"wcag_rule": "image-alt", "element_selector": "img"}],
    )
    assert result.status == "error"


async def test_none_snapshot_path_is_clean_error_not_unhandled_exception():
    """raw_html_snapshot_path is nullable on Page (Phase 1 — only set for
    status="loaded" pages, see docs/schema.md). main.py's caller already
    guards against calling in with None, but this function's own "never
    raises" contract (see module docstring) should hold regardless of the
    caller — Path(None) raises TypeError, not OSError, which would
    otherwise slip past the existing except clause uncaught."""
    result = await page_fixer.apply_verified_fixes_to_page(
        page_url="http://example.invalid/never-fetched",
        raw_html_snapshot_path=None,
        fixes=[
            page_fixer.FixToApply(
                wcag_rule="image-alt", element_selector="img",
                target_selector="img", proposed_code_diff='<img alt="x">',
            ),
        ],
        baseline=[{"wcag_rule": "image-alt", "element_selector": "img"}],
    )
    assert result.status == "error"
    assert "snapshot" in result.detail


async def test_empty_fixes_list_is_error():
    result = await page_fixer.apply_verified_fixes_to_page(
        page_url="http://example.invalid/never-fetched",
        raw_html_snapshot_path=str(DETECTOR_PAGES / "multi_violation.html"),
        fixes=[],
        baseline=[],
    )
    assert result.status == "error"


async def test_ignores_live_page_content_uses_snapshot_only():
    """The drift-safety guarantee, proven directly: page_url points at a
    domain that will never resolve (guaranteed connection failure if it
    were ever actually fetched), while raw_html_snapshot_path points at a
    real local fixture. apply_verified_fixes_to_page() never calls
    page.goto(page_url) — only page.set_content() on the snapshot, with
    page_url used solely as a <base href> string — so this must still
    succeed. If this ever regressed to fetching page_url directly, this
    test would fail with a connection error instead of "clean"."""
    snapshot_path = DETECTOR_PAGES / "multi_violation.html"
    fixes = [
        page_fixer.FixToApply(
            wcag_rule="image-alt", element_selector="img",
            target_selector="img", proposed_code_diff='<img src="x.jpg" alt="Hero image">',
        ),
        page_fixer.FixToApply(
            wcag_rule="tabindex", element_selector="div",
            target_selector="div", proposed_code_diff='<div tabindex="0">Focusable div</div>',
        ),
    ]
    baseline = [
        {"wcag_rule": "image-alt", "element_selector": "img"},
        {"wcag_rule": "tabindex", "element_selector": "div"},
    ]
    result = await page_fixer.apply_verified_fixes_to_page(
        page_url="http://this-domain-does-not-exist.invalid/page",
        raw_html_snapshot_path=str(snapshot_path),
        fixes=fixes,
        baseline=baseline,
    )
    assert result.status == "clean"
    assert 'base href="http://this-domain-does-not-exist.invalid/page"' in result.fixed_html


async def test_base_href_injected_for_relative_asset_resolution():
    snapshot_path = DETECTOR_PAGES / "multi_violation.html"
    fixes = [
        page_fixer.FixToApply(
            wcag_rule="image-alt", element_selector="img",
            target_selector="img", proposed_code_diff='<img src="x.jpg" alt="Hero image">',
        ),
    ]
    baseline = [
        {"wcag_rule": "image-alt", "element_selector": "img"},
        {"wcag_rule": "tabindex", "element_selector": "div"},
    ]
    result = await page_fixer.apply_verified_fixes_to_page(
        page_url="https://example.com/some/page.html",
        raw_html_snapshot_path=str(snapshot_path),
        fixes=fixes,
        baseline=baseline,
    )
    assert result.status == "clean"
    assert 'base href="https://example.com/some/page.html"' in result.fixed_html
