"""
test_detector.py — Phase 2.5b regression coverage for detector.py.

Each fixture under fixtures/detector_pages/ was hand-run against the real
axe-core detector this session before being trusted here (not guessed) —
see PLAN.md's 2.5b session-log entry for the raw verification output. Each
fixture is built "fully compliant except for the one targeted issue" (valid
lang, a skip-link, a landmark, other inputs correctly labeled, etc.) so a
test asserting the exact violation set isn't accidentally passing because
of noise from the other 8 locked rules.

No crawler involved: a real headless Chromium page is loaded directly
against the local test server (fixtures/server.py) and handed straight to
detect_violations(), matching detect_violations()'s actual contract (an
already-loaded Page, however it got loaded).

Deliberately not a pytest fixture: launching Playwright inside a
`@pytest.fixture` (async generator) reliably hung this session — zero
output, zero CPU on the spawned chrome-headless-shell processes, past the
first test's collection line — regardless of whether the fixture used
`async with async_playwright() as p: ... yield ...` or explicit
`.start()`/`.stop()`, and regardless of fixture scope (module or
function). A standalone script doing the identical launch+goto+detect
sequence outside pytest completed in well under a second, ruling out
detector.py/browser logic itself. Inlining the whole sequence directly in
the test body (what `_violations_for` below does, called straight from
each test) is the pattern that was actually confirmed not to hang.
"""
from playwright.async_api import async_playwright

from detector import detect_violations


async def _violations_for(test_server, filename: str):
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(headless=True)
        try:
            pg = await browser.new_page()
            await pg.goto(f"{test_server.base_url}/detector_pages/{filename}", wait_until="load")
            return await detect_violations(pg)
        finally:
            await browser.close()
    finally:
        await playwright.stop()


async def test_missing_alt_detected(test_server):
    v = await _violations_for(test_server, "missing_alt.html")
    assert len(v) == 1 and v[0].wcag_rule == "image-alt" and v[0].severity == "critical"


async def test_input_image_alt_detected(test_server):
    v = await _violations_for(test_server, "input_image_alt.html")
    assert len(v) == 1 and v[0].wcag_rule == "input-image-alt" and v[0].severity == "critical"


async def test_missing_label_detected(test_server):
    v = await _violations_for(test_server, "missing_label.html")
    assert len(v) == 1 and v[0].wcag_rule == "label" and v[0].severity == "critical"


async def test_missing_button_name_detected(test_server):
    v = await _violations_for(test_server, "missing_button_name.html")
    assert len(v) == 1 and v[0].wcag_rule == "button-name" and v[0].severity == "critical"


async def test_aria_input_field_name_detected(test_server):
    v = await _violations_for(test_server, "aria_input_field_name.html")
    assert len(v) == 1 and v[0].wcag_rule == "aria-input-field-name" and v[0].severity == "serious"


async def test_positive_tabindex_detected(test_server):
    v = await _violations_for(test_server, "positive_tabindex.html")
    assert len(v) == 1 and v[0].wcag_rule == "tabindex" and v[0].severity == "serious"


async def test_missing_lang_detected(test_server):
    v = await _violations_for(test_server, "missing_lang.html")
    assert len(v) == 1 and v[0].wcag_rule == "html-has-lang" and v[0].severity == "serious"


async def test_invalid_lang_detected(test_server):
    v = await _violations_for(test_server, "invalid_lang.html")
    assert len(v) == 1 and v[0].wcag_rule == "html-lang-valid" and v[0].severity == "serious"


async def test_bad_list_detected(test_server):
    v = await _violations_for(test_server, "bad_list.html")
    assert len(v) == 1 and v[0].wcag_rule == "list" and v[0].severity == "serious"


async def test_bad_listitem_detected(test_server):
    v = await _violations_for(test_server, "bad_listitem.html")
    assert len(v) == 1 and v[0].wcag_rule == "listitem" and v[0].severity == "serious"


async def test_bad_definition_list_detected(test_server):
    v = await _violations_for(test_server, "bad_definition_list.html")
    assert len(v) == 1 and v[0].wcag_rule == "definition-list" and v[0].severity == "serious"


async def test_missing_link_name_detected(test_server):
    v = await _violations_for(test_server, "missing_link_name.html")
    assert len(v) == 1 and v[0].wcag_rule == "link-name" and v[0].severity == "serious"


async def test_color_contrast_detected(test_server):
    v = await _violations_for(test_server, "color_contrast.html")
    assert len(v) == 1 and v[0].wcag_rule == "color-contrast" and v[0].severity == "serious"


async def test_clean_fixture_has_no_violations(test_server):
    v = await _violations_for(test_server, "clean.html")
    assert v == []


async def test_multi_violation_fixture_produces_one_row_per_rule(test_server):
    v = await _violations_for(test_server, "multi_violation.html")
    rules = {viol.wcag_rule for viol in v}
    assert rules == {"image-alt", "tabindex"}
    assert len(v) == 2  # one row per (rule, element), not merged


async def test_bypass_incomplete_gap_now_surfaces_as_needs_review(test_server):
    """Phase 2.6 closes the reviewOnFail gap (see design.md Section 3):
    axe-core marks `bypass` reviewOnFail=true, so a genuine failure lands in
    axe's `incomplete` array, not `violations`. detect_violations() now also
    reads `incomplete` for this rule and tags the result
    detection_confidence="needs_review" rather than silently dropping it.
    no_bypass.html has no skip-link, heading, or landmark and genuinely
    fails the rule (confirmed via a raw axe run against this exact fixture
    during 2.5b planning, and re-confirmed with `impact` present/non-null
    during 2.6 planning)."""
    v = await _violations_for(test_server, "no_bypass.html")
    bypass = [viol for viol in v if viol.wcag_rule == "bypass"]
    assert len(bypass) == 1
    assert bypass[0].detection_confidence == "needs_review"
    assert bypass[0].severity != "unknown"


async def test_duplicate_id_aria_incomplete_gap_now_surfaces_as_needs_review(test_server):
    """Same reviewOnFail gap as bypass (see design.md), now closed the same
    way. duplicate_id_aria.html has an aria-labelledby-referenced id
    duplicated elsewhere on the page — a genuine axe failure, confirmed via
    a raw axe run to land in `incomplete`, not `violations`."""
    v = await _violations_for(test_server, "duplicate_id_aria.html")
    dup = [viol for viol in v if viol.wcag_rule == "duplicate-id-aria"]
    assert len(dup) == 1
    assert dup[0].detection_confidence == "needs_review"
    assert dup[0].severity != "unknown"


async def test_other_locked_rules_never_get_needs_review(test_server):
    """Regression guard on scope, not just on detection working: Phase 2.6
    only reads `incomplete` for REVIEW_ON_FAIL_RULE_IDS (bypass,
    duplicate-id-aria). Every other locked rule's existing fixture must
    still only ever produce detection_confidence="confirmed" — confirming
    the fix didn't start reading `incomplete` more broadly than intended."""
    fixtures = [
        "missing_alt.html", "input_image_alt.html", "missing_label.html",
        "missing_button_name.html", "aria_input_field_name.html",
        "positive_tabindex.html", "missing_lang.html", "invalid_lang.html",
        "bad_list.html", "bad_listitem.html", "bad_definition_list.html",
        "missing_link_name.html", "color_contrast.html",
    ]
    for filename in fixtures:
        v = await _violations_for(test_server, filename)
        assert v, f"{filename} produced no violations at all"
        assert all(viol.detection_confidence == "confirmed" for viol in v), (
            f"{filename} unexpectedly produced a needs_review violation"
        )
