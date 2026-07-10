"""
test_dashboard_endpoints.py — Phase 4 regression coverage for the new
dashboard-facing endpoints in main.py: GET /sites, GET /scans,
POST /fixes/{id}/approval, POST /pages/{id}/generate-fixed-page,
GET /pages/{id}/download-fixed.

LLM_MOCK=true (forced in .env.test) means a fix produced by the real
/scan -> reasoning-graph pipeline never actually reaches
verification_status="verified" — llm_client.py's mock Developer output
(`target_selector="mock-selector"`) doesn't resolve against a real page, so
verify_fix() always lands on manual_review in mock mode. These tests
instead build Violation/Fix/Approval rows directly via async_session_factory
(same test-DB-bound engine main.py itself uses, confirmed correctly
repointed by api/conftest.py's DATABASE_URL override before `import main`)
— exercising the new endpoints' own logic, not re-proving the reasoning
graph (already covered in tests/graph/).

Reuses fixtures/detector_pages/multi_violation.html (image-alt 'img' +
tabindex 'div', confirmed live in test_page_fixer.py) as the on-disk
raw_html_snapshot_path stand-in.
"""
import uuid
from datetime import datetime, timezone

from db import async_session_factory
from fixtures.server import FIXTURES_DIR
from models import Fix, FixVerificationStatus, Page, Scan, ScanStatus, Site, Violation, ViolationStatus

MULTI_VIOLATION_SNAPSHOT = str(FIXTURES_DIR / "detector_pages" / "multi_violation.html")


async def _create_page_with_fixes(
    verification_status=FixVerificationStatus.verified,
    raw_html_snapshot_path=MULTI_VIOLATION_SNAPSHOT,
):
    """Creates Site -> Scan -> Page -> 2 Violations (image-alt/img,
    tabindex/div) -> 2 Fixes with real, live-confirmed working diffs.
    Returns (page_id, fix_id_image_alt, fix_id_tabindex)."""
    suffix = uuid.uuid4().hex[:12]
    async with async_session_factory() as db:
        site = Site(url=f"http://dashboard-test-{suffix}.invalid/")
        db.add(site)
        await db.flush()

        scan = Scan(site_id=site.id, status=ScanStatus.done, started_at=datetime.now(timezone.utc))
        db.add(scan)
        await db.flush()

        page = Page(
            scan_id=scan.id, url=f"http://dashboard-test-{suffix}.invalid/page.html",
            raw_html_snapshot_path=raw_html_snapshot_path, status="loaded",
        )
        db.add(page)
        await db.flush()

        v_alt = Violation(
            page_id=page.id, wcag_rule="image-alt", element_selector="img",
            severity="critical", status=ViolationStatus.open,
        )
        v_tab = Violation(
            page_id=page.id, wcag_rule="tabindex", element_selector="div",
            severity="serious", status=ViolationStatus.open,
        )
        db.add_all([v_alt, v_tab])
        await db.flush()

        fix_alt = Fix(
            violation_id=v_alt.id, target_selector="img",
            proposed_code_diff='<img src="x.jpg" alt="Hero image">',
            verification_status=verification_status,
        )
        fix_tab = Fix(
            violation_id=v_tab.id, target_selector="div",
            proposed_code_diff='<div tabindex="0">Focusable div</div>',
            verification_status=verification_status,
        )
        db.add_all([fix_alt, fix_tab])
        await db.commit()

        return page.id, fix_alt.id, fix_tab.id


async def test_list_sites_shows_latest_scan_status(api_client):
    suffix = uuid.uuid4().hex[:12]
    async with async_session_factory() as db:
        site = Site(url=f"http://sites-list-test-{suffix}.invalid/")
        db.add(site)
        await db.flush()
        db.add(Scan(site_id=site.id, status=ScanStatus.failed))
        await db.flush()
        newer_scan = Scan(site_id=site.id, status=ScanStatus.done)
        db.add(newer_scan)
        await db.commit()
        site_id = site.id

    resp = await api_client.get("/sites")
    assert resp.status_code == 200
    matching = [s for s in resp.json() if s["id"] == site_id]
    assert len(matching) == 1
    assert matching[0]["latest_scan_status"] == "done"


async def test_list_scans_filters_by_site_id(api_client):
    suffix = uuid.uuid4().hex[:12]
    async with async_session_factory() as db:
        site_a = Site(url=f"http://scans-filter-a-{suffix}.invalid/")
        site_b = Site(url=f"http://scans-filter-b-{suffix}.invalid/")
        db.add_all([site_a, site_b])
        await db.flush()
        db.add(Scan(site_id=site_a.id, status=ScanStatus.done))
        db.add(Scan(site_id=site_b.id, status=ScanStatus.done))
        await db.commit()
        site_a_id = site_a.id

    resp = await api_client.get("/scans", params={"site_id": site_a_id})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["site_id"] == site_a_id


async def test_create_approval_404_for_missing_fix(api_client):
    resp = await api_client.post("/fixes/999999999/approval", json={"decision": "approved", "approver": "tester"})
    assert resp.status_code == 404


async def test_create_approval_requires_verified_fix(api_client):
    _, fix_id, _ = await _create_page_with_fixes(verification_status=FixVerificationStatus.manual_review)
    resp = await api_client.post(f"/fixes/{fix_id}/approval", json={"decision": "approved", "approver": "tester"})
    assert resp.status_code == 400


async def test_create_approval_success(api_client):
    _, fix_id, _ = await _create_page_with_fixes()
    resp = await api_client.post(f"/fixes/{fix_id}/approval", json={"decision": "approved", "approver": "tester"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["fix_id"] == fix_id
    assert body["decision"] == "approved"
    assert body["approver"] == "tester"


async def test_generate_fixed_page_full_approval_clean(api_client):
    page_id, fix_alt_id, fix_tab_id = await _create_page_with_fixes()
    for fix_id in (fix_alt_id, fix_tab_id):
        resp = await api_client.post(f"/fixes/{fix_id}/approval", json={"decision": "approved", "approver": "tester"})
        assert resp.status_code == 201

    resp = await api_client.post(f"/pages/{page_id}/generate-fixed-page")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "clean"
    assert body["fixes_included_count"] == 2
    assert body["fixes_pending_count"] == 0
    assert body["download_available"] is True

    download = await api_client.get(f"/pages/{page_id}/download-fixed")
    assert download.status_code == 200
    assert 'alt="Hero image"' in download.text


async def test_generate_fixed_page_partial_approval_still_clean(api_client):
    """Only image-alt approved; tabindex left pending. The unapproved
    violation is expected to remain — that's not a failure, per the
    explicit "partial approval allowed" decision — but the response must
    say so plainly via the counts, not silently."""
    page_id, fix_alt_id, _fix_tab_id = await _create_page_with_fixes()
    resp = await api_client.post(f"/fixes/{fix_alt_id}/approval", json={"decision": "approved", "approver": "tester"})
    assert resp.status_code == 201

    resp = await api_client.post(f"/pages/{page_id}/generate-fixed-page")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "clean"
    assert body["fixes_included_count"] == 1
    assert body["fixes_pending_count"] == 1
    assert "1/2" in body["detail"]


async def test_generate_fixed_page_zero_approved_is_400(api_client):
    page_id, _, _ = await _create_page_with_fixes()
    resp = await api_client.post(f"/pages/{page_id}/generate-fixed-page")
    assert resp.status_code == 400


async def test_generate_fixed_page_null_snapshot_path_is_clean_400(api_client):
    """raw_html_snapshot_path is nullable on Page — only set for
    status="loaded" pages per docs/schema.md, and page_fixer.py now
    depends on it being populated. A page with status="loaded" but a null
    snapshot path shouldn't be reachable via the real crawler (crawler.py
    sets both together), but nothing in the schema enforces that
    invariant, and page_fixer.py is a new, second consumer of this column
    beyond its original use — must return a clean 400, not an unhandled
    500, if that invariant is ever violated."""
    page_id, fix_id, _ = await _create_page_with_fixes(raw_html_snapshot_path=None)
    approve = await api_client.post(f"/fixes/{fix_id}/approval", json={"decision": "approved", "approver": "tester"})
    assert approve.status_code == 201

    resp = await api_client.post(f"/pages/{page_id}/generate-fixed-page")
    assert resp.status_code == 400
    assert "snapshot" in resp.json()["detail"]


async def test_download_fixed_page_404_before_generation(api_client):
    page_id, _, _ = await _create_page_with_fixes()
    resp = await api_client.get(f"/pages/{page_id}/download-fixed")
    assert resp.status_code == 404


async def test_get_scan_reflects_latest_approval_decision(api_client):
    """The Review & Approve tab needs to survive a page refresh without
    forgetting prior decisions — GET /scan/{id} must reflect the most
    recent Approval row per fix, not just whatever verification_status
    says."""
    page_id, fix_alt_id, fix_tab_id = await _create_page_with_fixes()

    async with async_session_factory() as db:
        page = await db.get(Page, page_id)
        scan_id = page.scan_id

    resp = await api_client.get(f"/scan/{scan_id}")
    fixes_before = {
        v["fix"]["id"]: v["fix"]["latest_approval_decision"]
        for p in resp.json()["pages"] for v in p["violations"] if v["fix"]
    }
    assert fixes_before[fix_alt_id] is None
    assert fixes_before[fix_tab_id] is None

    await api_client.post(f"/fixes/{fix_alt_id}/approval", json={"decision": "approved", "approver": "tester"})
    await api_client.post(f"/fixes/{fix_tab_id}/approval", json={"decision": "rejected", "approver": "tester"})

    resp = await api_client.get(f"/scan/{scan_id}")
    fixes_after = {
        v["fix"]["id"]: v["fix"]["latest_approval_decision"]
        for p in resp.json()["pages"] for v in p["violations"] if v["fix"]
    }
    assert fixes_after[fix_alt_id] == "approved"
    assert fixes_after[fix_tab_id] == "rejected"


async def test_performance_summary_shape(api_client):
    """Smoke test only — cost_report.py's own test suite
    (tests/cost_report/) covers the actual metric correctness; this just
    confirms the endpoint wires those functions together without error and
    the honest pr_metrics=None placeholder (Phase 4 doesn't open real PRs —
    see design.md) is present, not silently omitted."""
    resp = await api_client.get("/performance/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert "agent_cost_summary" in body
    assert "scan_performance_summary" in body
    assert "accessibility_score_trend" in body
    assert body["pr_metrics"] is None
