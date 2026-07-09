"""
cost_report.py — Phase 3's real cost-comparison measurement. Queries
llm_call_logs and fixes for actual logged numbers (avg tokens/agent,
cache-hit %, model_used breakdown, Fix verification-status distribution,
retry-count-1 %) — nothing here is invented or estimated, per CLAUDE.md's
rule that any real number ending up in EVALUATION.md/a completion report
must be traceable to actual logged data.

compute_agent_cost_summary() is a plain importable async function (not
just a CLI entry point) so Phase 4's dashboard can reuse the same query
logic later rather than duplicating it.

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
from models import Fix, LlmCallLog


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
            "models_used": set(),
        })
        bucket["call_count"] += 1
        bucket["total_tokens"] += row.tokens_used
        if row.cache_hit:
            bucket["cache_hits"] += 1
        bucket["models_used"].add(row.model_used)

    agent_summary = {}
    for agent, bucket in by_agent.items():
        call_count = bucket["call_count"]
        agent_summary[agent] = {
            "call_count": call_count,
            "avg_tokens_per_call": bucket["total_tokens"] / call_count if call_count else 0,
            "cache_hit_rate": bucket["cache_hits"] / call_count if call_count else 0,
            "models_used": sorted(bucket["models_used"]),
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


async def _main() -> None:
    async with async_session_factory() as db:
        summary = await compute_agent_cost_summary(db)
    print(json.dumps(summary, indent=2))
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(_main())
