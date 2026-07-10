"""
test_cost_report.py — Phase 4 regression coverage for cost_report.py's new
System Performance metrics: _percentile, compute_scan_performance_summary,
compute_accessibility_score_trend, and the latency/success-rate fields
added to compute_agent_cost_summary's per-agent breakdown.

llm_call_logs/scans/pages/violations are real, persistent tables the full
test suite writes to across many other test files and is never truncated
between pytest runs (same convention test_llm_client_cache.py documents) —
compute_scan_performance_summary/compute_agent_cost_summary aggregate over
*all* rows, with no site_id scoping, so exact-value assertions against a
shared table are not reliable. Tests instead capture a before/after
snapshot and assert the delta introduced by this test's own known inserts,
except compute_accessibility_score_trend, which is scoped to a single
uuid-suffixed site_id and can assert exact values directly.
"""
import uuid
from datetime import datetime, timedelta, timezone

import cost_report
from db import async_session_factory
from models import AgentName, LlmCallLog, Page, Scan, ScanStatus, Site, Violation, ViolationStatus


def test_percentile_empty_and_single():
    assert cost_report._percentile([], 50) is None
    assert cost_report._percentile([42.0], 95) == 42.0


def test_percentile_matches_known_values():
    # 1..10: median (p50) is 5.5, p100 is 10, p0 is 1 — standard
    # linear-interpolation percentile, hand-verified.
    values = [float(i) for i in range(1, 11)]
    assert cost_report._percentile(values, 50) == 5.5
    assert cost_report._percentile(values, 0) == 1.0
    assert cost_report._percentile(values, 100) == 10.0


async def test_scan_performance_summary_reflects_new_scans():
    async with async_session_factory() as db:
        before = await cost_report.compute_scan_performance_summary(db)

    suffix = uuid.uuid4().hex[:12]
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with async_session_factory() as db:
        site = Site(url=f"http://perf-summary-test-{suffix}.invalid/")
        db.add(site)
        await db.flush()
        db.add_all([
            Scan(site_id=site.id, status=ScanStatus.done, started_at=t0, completed_at=t0 + timedelta(seconds=10)),
            Scan(site_id=site.id, status=ScanStatus.failed, started_at=t0, completed_at=t0 + timedelta(seconds=2)),
        ])
        await db.commit()

    async with async_session_factory() as db:
        after = await cost_report.compute_scan_performance_summary(db)

    assert after["total_scans"] == before["total_scans"] + 2
    before_done = round(before["scan_success_rate"] * before["total_scans"])
    after_done = round(after["scan_success_rate"] * after["total_scans"])
    assert after_done == before_done + 1


async def test_accessibility_score_trend_ratio_excludes_fixed_violations():
    suffix = uuid.uuid4().hex[:12]
    async with async_session_factory() as db:
        site = Site(url=f"http://score-trend-test-{suffix}.invalid/")
        db.add(site)
        await db.flush()
        scan = Scan(site_id=site.id, status=ScanStatus.done, completed_at=datetime.now(timezone.utc))
        db.add(scan)
        await db.flush()
        page1 = Page(scan_id=scan.id, url="http://score-trend/1", status="loaded")
        page2 = Page(scan_id=scan.id, url="http://score-trend/2", status="loaded")
        db.add_all([page1, page2])
        await db.flush()
        db.add_all([
            Violation(page_id=page1.id, wcag_rule="image-alt", element_selector="img", severity="critical", status=ViolationStatus.open),
            Violation(page_id=page1.id, wcag_rule="tabindex", element_selector="div", severity="serious", status=ViolationStatus.open),
            # Fixed — must not count toward open_violations.
            Violation(page_id=page2.id, wcag_rule="link-name", element_selector="a", severity="serious", status=ViolationStatus.fixed),
        ])
        await db.commit()
        scan_id, site_id = scan.id, site.id

    async with async_session_factory() as db:
        trend = await cost_report.compute_accessibility_score_trend(db, site_id=site_id)

    matching = [t for t in trend if t["scan_id"] == scan_id]
    assert len(matching) == 1
    # 2 open violations across 2 pages = 1.0, the fixed one excluded.
    assert matching[0]["open_violations_per_page"] == 1.0


async def test_accessibility_score_trend_scoped_to_site_id():
    suffix = uuid.uuid4().hex[:12]
    async with async_session_factory() as db:
        site_a = Site(url=f"http://score-trend-scope-a-{suffix}.invalid/")
        site_b = Site(url=f"http://score-trend-scope-b-{suffix}.invalid/")
        db.add_all([site_a, site_b])
        await db.flush()
        scan_a = Scan(site_id=site_a.id, status=ScanStatus.done, completed_at=datetime.now(timezone.utc))
        scan_b = Scan(site_id=site_b.id, status=ScanStatus.done, completed_at=datetime.now(timezone.utc))
        db.add_all([scan_a, scan_b])
        await db.flush()
        db.add_all([
            Page(scan_id=scan_a.id, url="http://a/1", status="loaded"),
            Page(scan_id=scan_b.id, url="http://b/1", status="loaded"),
        ])
        await db.commit()
        site_a_id, scan_a_id, scan_b_id = site_a.id, scan_a.id, scan_b.id

    async with async_session_factory() as db:
        trend = await cost_report.compute_accessibility_score_trend(db, site_id=site_a_id)

    scan_ids = {t["scan_id"] for t in trend}
    assert scan_a_id in scan_ids
    assert scan_b_id not in scan_ids


async def test_agent_cost_summary_tracks_new_model_and_call_count():
    suffix = uuid.uuid4().hex[:12]
    async with async_session_factory() as db:
        before = await cost_report.compute_agent_cost_summary(db)
    before_reviewer_calls = before["by_agent"].get("Reviewer", {"call_count": 0})["call_count"]

    async with async_session_factory() as db:
        db.add_all([
            LlmCallLog(
                agent_name=AgentName.Reviewer, latency_ms=100, tokens_used=50,
                model_used=f"test-model-{suffix}", cache_hit=False, is_mock=False,
                created_at=datetime.now(timezone.utc),
            ),
            LlmCallLog(
                agent_name=AgentName.Reviewer, latency_ms=200, tokens_used=50,
                model_used=f"test-model-{suffix}", cache_hit=False, is_mock=False,
                error="boom", error_type="unknown", created_at=datetime.now(timezone.utc),
            ),
        ])
        await db.commit()

    async with async_session_factory() as db:
        after = await cost_report.compute_agent_cost_summary(db)

    reviewer_after = after["by_agent"]["Reviewer"]
    assert reviewer_after["call_count"] == before_reviewer_calls + 2
    assert f"test-model-{suffix}" in reviewer_after["models_used"]
    assert reviewer_after["latency_ms_median"] is not None
    assert reviewer_after["latency_ms_p95"] is not None
