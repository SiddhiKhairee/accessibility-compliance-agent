"""
cost_report.py — Phase 3's real cost-comparison measurement, extended in
Phase 4 with the System Performance dashboard tab's remaining metrics.
Queries llm_call_logs/fixes/scans/pages/violations for actual logged
numbers — nothing here is invented or estimated, per CLAUDE.md's rule that
any real number ending up in EVALUATION.md/a completion report must be
traceable to actual logged data.

Every compute_*() function here is a plain importable async function (not
just a CLI entry point) so main.py's GET /performance/summary can reuse the
same query logic rather than duplicating it.

Run from inside backend/app/ (matching the flat-import convention):

    cd backend/app
    python cost_report.py
"""
import asyncio
import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import async_session_factory, dispose_engine
from models import Fix, LlmCallLog, Page, Scan, ScanStatus, Violation, ViolationStatus


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    """Standard linear-interpolation percentile — no numpy dependency
    (not in requirements.txt, and not worth adding for this)."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


async def compute_agent_cost_summary(
    db: AsyncSession, since: datetime | None = None, until: datetime | None = None,
) -> dict:
    log_query = select(LlmCallLog).where(LlmCallLog.is_mock.is_(False))
    if since is not None:
        log_query = log_query.where(LlmCallLog.created_at >= since)
    if until is not None:
        log_query = log_query.where(LlmCallLog.created_at < until)
    logs = (await db.execute(log_query)).scalars().all()

    by_agent: dict[str, dict] = {}
    for row in logs:
        agent = row.agent_name.value
        bucket = by_agent.setdefault(agent, {
            "call_count": 0, "total_tokens": 0, "cache_hits": 0,
            "models_used": set(), "latencies_ms": [], "error_count": 0,
        })
        bucket["call_count"] += 1
        bucket["total_tokens"] += row.tokens_used
        if row.cache_hit:
            bucket["cache_hits"] += 1
        bucket["models_used"].add(row.model_used)
        bucket["latencies_ms"].append(row.latency_ms)
        if row.error is not None:
            bucket["error_count"] += 1

    agent_summary = {}
    for agent, bucket in by_agent.items():
        call_count = bucket["call_count"]
        sorted_latencies = sorted(bucket["latencies_ms"])
        agent_summary[agent] = {
            "call_count": call_count,
            "avg_tokens_per_call": bucket["total_tokens"] / call_count if call_count else 0,
            "cache_hit_rate": bucket["cache_hits"] / call_count if call_count else 0,
            "models_used": sorted(bucket["models_used"]),
            "latency_ms_median": _percentile(sorted_latencies, 50),
            "latency_ms_p95": _percentile(sorted_latencies, 95),
            "success_rate": (call_count - bucket["error_count"]) / call_count if call_count else 0,
        }

    fix_status_counts = dict((await db.execute(
        select(Fix.verification_status, func.count()).group_by(Fix.verification_status)
    )).all())
    fix_status_summary = {
        (status.value if status is not None else "unset"): count
        for status, count in fix_status_counts.items()
    }

    total_fixes = (await db.execute(select(func.count()).select_from(Fix))).scalar_one()
    retried_fixes = (await db.execute(
        select(func.count()).select_from(Fix).where(Fix.retry_count > 0)
    )).scalar_one()

    return {
        "by_agent": agent_summary,
        "fix_verification_status_counts": fix_status_summary,
        "fix_retry_rate": retried_fixes / total_fixes if total_fixes else 0,
        "total_fixes": total_fixes,
    }


async def compute_scan_performance_summary(db: AsyncSession) -> dict:
    """Throughput/pipeline-time/success-rate, computed from real
    scans.status/started_at/completed_at — no invented numbers."""
    rows = (await db.execute(select(Scan.status, Scan.started_at, Scan.completed_at))).all()
    total_scans = len(rows)
    durations_s = sorted(
        (r.completed_at - r.started_at).total_seconds()
        for r in rows if r.started_at is not None and r.completed_at is not None
    )
    done_count = sum(1 for r in rows if r.status == ScanStatus.done)

    return {
        "total_scans": total_scans,
        "scan_success_rate": done_count / total_scans if total_scans else 0,
        "pipeline_time_median_s": _percentile(durations_s, 50),
        "pipeline_time_p95_s": _percentile(durations_s, 95),
    }


async def compute_accessibility_score_trend(db: AsyncSession, site_id: int | None = None) -> list[dict]:
    """Confirmed definition (Phase 4 planning, not previously defined
    anywhere in schema.md): open_violations / page_count per scan, trended
    across a site's repeat scans by scans.completed_at. A direct ratio of
    two already-logged counts, no invented weighting or composite formula —
    lower is better, fully traceable. Only scans that reached "done" are
    included (an in-progress/failed scan has no stable violation count to
    report)."""
    query = (
        select(
            Scan.id, Scan.site_id, Scan.completed_at,
            func.count(func.distinct(Page.id)).label("page_count"),
            func.count(Violation.id).filter(Violation.status == ViolationStatus.open).label("open_violations"),
        )
        .select_from(Scan)
        .join(Page, Page.scan_id == Scan.id)
        .outerjoin(Violation, Violation.page_id == Page.id)
        .where(Scan.status == ScanStatus.done)
        .group_by(Scan.id, Scan.site_id, Scan.completed_at)
        .order_by(Scan.completed_at)
    )
    if site_id is not None:
        query = query.where(Scan.site_id == site_id)

    rows = (await db.execute(query)).all()
    return [
        {
            "scan_id": r.id,
            "site_id": r.site_id,
            "completed_at": r.completed_at,
            "open_violations_per_page": r.open_violations / r.page_count if r.page_count else None,
        }
        for r in rows
    ]


async def _main() -> None:
    async with async_session_factory() as db:
        summary = {
            "agent_cost_summary": await compute_agent_cost_summary(db),
            "scan_performance_summary": await compute_scan_performance_summary(db),
            "accessibility_score_trend": await compute_accessibility_score_trend(db),
        }
    print(json.dumps(summary, indent=2, default=str))
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(_main())
