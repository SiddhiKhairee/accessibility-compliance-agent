"""
eval_runner.py — Phase 5 Pass 1 orchestrator: crawl+detect (free) then
Reviewer-only confidence scoring (real Groq calls, budget-gated) across
eval/eval_corpus_30_sites.csv.

Resumable via eval/progress_pass1.json: every site's crawl/detect result
and every violation's Reviewer outcome (including html_snippet/message, not
just its identity) is checkpointed to disk immediately, so a stop mid-run
(Ctrl-C, budget threshold, crash) resumes from exactly where it left off —
never re-crawling a done site or re-spending a Groq call on a violation
already reviewed. html_snippet/message have to live in the manifest, not
just be read from an in-memory crawl result, precisely so a violation whose
site already finished crawling in an earlier process can still be reviewed
on a later resumed run without re-crawling that site.

Fully file-based: no Site/Scan/Page/Violation DB rows are created for
corpus sites. The only DB write this triggers is the one call_llm() already
makes for any real Reviewer call (its llm_call_logs row) — exactly the
table the budget guard reads.

Run from inside backend/app/ (matching cost_report.py's convention):

    cd backend/app
    python eval_runner.py
"""
import asyncio
import csv
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import crawler
import llm_client
from config import settings
from db import async_session_factory, dispose_engine
from graph import reviewer_node
from models import LlmCallLog

logger = logging.getLogger(__name__)

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
CORPUS_PATH = EVAL_DIR / "eval_corpus_30_sites.csv"
PROGRESS_PASS1_PATH = EVAL_DIR / "progress_pass1.json"
SNAPSHOT_DIR = EVAL_DIR / "labeled_raw"


class LlmMockEnabledError(RuntimeError):
    """Raised when LLM_MOCK=true — mock data must never enter real
    precision/recall/calibration numbers (CLAUDE.md's ban on invented
    metrics)."""


def _assert_llm_not_mocked() -> None:
    if llm_client._mock_enabled():
        raise LlmMockEnabledError(
            "LLM_MOCK=true — refusing to run eval Pass 1 with mock data. "
            "Unset LLM_MOCK and re-run."
        )


def _start_of_day_utc(now: datetime) -> datetime:
    return now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


async def count_real_calls_today(
    db: AsyncSession, model: str = llm_client.MODEL_NAME, now: datetime | None = None,
) -> int:
    """Real (is_mock=False, cache_hit=False) calls to `model` since UTC
    midnight. Filters by model, not agent_name, since Groq's RPD cap is
    per-model-per-account — this also captures any concurrent production
    Reviewer/Developer traffic on the same model, not just this eval run's
    own calls. `now` is injectable so tests never depend on a real day
    boundary."""
    since = _start_of_day_utc(now or datetime.now(timezone.utc))
    result = await db.execute(
        select(func.count()).select_from(LlmCallLog).where(
            LlmCallLog.is_mock.is_(False),
            LlmCallLog.cache_hit.is_(False),
            LlmCallLog.model_used == model,
            LlmCallLog.created_at >= since,
        )
    )
    return result.scalar_one()


def should_stop_for_budget(current_count: int, daily_cap: int, safety_margin_pct: float) -> bool:
    """Pure function: stop once current_count reaches the safety-margined
    threshold, not the literal cap — leaves headroom for other concurrent
    Groq usage on the same account/model."""
    return current_count >= daily_cap * safety_margin_pct


def load_corpus(path: Path = CORPUS_PATH) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_or_init_manifest(path: Path, corpus: list[dict]) -> dict:
    """Creates the all-pending shape from `corpus` if `path` doesn't exist
    yet; loads as-is otherwise — never resets existing progress."""
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {
        "run_started_at": None,
        "last_updated_at": None,
        "budget_stopped": False,
        "sites": {
            row["site_id"]: {
                "url": row["url"],
                "tier": row["tier"],
                "crawl_detect_status": "pending",
                "crawl_detect_failure_reason": None,
                "pages": [],
            }
            for row in corpus
        },
    }


def save_manifest(path: Path, manifest: dict) -> None:
    """Atomic write (tmp file + os.replace) so a crash mid-write can't
    corrupt the manifest a resume depends on."""
    manifest["last_updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    os.replace(tmp_path, path)


def _violation_entry(v: crawler.Violation) -> dict:
    return {
        "wcag_rule": v.wcag_rule,
        "element_selector": v.element_selector,
        "html_snippet": v.html_snippet,
        "message": v.message,
        "reviewer_status": "pending",
        "confidence_score": None,
        "confirmed": None,
        "failure_reason": None,
        "error_type": None,
    }


def _page_entry(pg: crawler.CrawledPage) -> dict:
    return {
        "url": pg.url,
        "load_status": pg.status,
        "load_failure_reason": pg.failure_reason,
        "snapshot_path": pg.snapshot_path,
        "violations": [_violation_entry(v) for v in pg.violations],
    }


async def run_pass1(
    db: AsyncSession,
    *,
    corpus_path: Path = CORPUS_PATH,
    manifest_path: Path = PROGRESS_PASS1_PATH,
    snapshot_dir: Path = SNAPSHOT_DIR,
    daily_cap: int | None = None,
    safety_margin_pct: float | None = None,
    max_pages: int = crawler.DEFAULT_MAX_PAGES,
    max_depth: int = crawler.DEFAULT_MAX_DEPTH,
) -> dict:
    """Pass 1: crawl+detect every corpus site not yet done (free, runs to
    completion first), then run the Reviewer (only — not the full 4-node
    graph) on every violation not yet reviewed, checking the daily-budget
    guard before each real call. Split into two sequential loops so a
    violation-heavy site can't block later sites from being crawled —
    crawling has no Groq cost and should never be gated behind review
    budget. Stops cleanly (no exception) and returns budget_stopped=True
    the moment the guard trips, with the manifest already saved reflecting
    exactly what got done."""
    _assert_llm_not_mocked()

    daily_cap = settings.EVAL_DAILY_CALL_CAP if daily_cap is None else daily_cap
    safety_margin_pct = (
        settings.EVAL_DAILY_CAP_SAFETY_MARGIN_PCT if safety_margin_pct is None else safety_margin_pct
    )
    logger.info(
        "eval_runner Pass 1: daily_cap=%s safety_margin_pct=%s — confirm this matches "
        "console.groq.com/settings/limits for your account before a real run",
        daily_cap, safety_margin_pct,
    )

    corpus = load_corpus(corpus_path)
    manifest = load_or_init_manifest(manifest_path, corpus)
    if manifest["run_started_at"] is None:
        manifest["run_started_at"] = datetime.now(timezone.utc).isoformat()
    manifest["budget_stopped"] = False
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    sites_crawled = 0
    violations_reviewed = 0

    # Pass 1a: crawl+detect every site not yet done. No Groq cost, no budget
    # check — runs the whole corpus in one call regardless of violation counts.
    for row in corpus:
        site_entry = manifest["sites"][row["site_id"]]
        if site_entry["crawl_detect_status"] == "done":
            continue

        try:
            pages = await crawler.crawl_site(
                site_entry["url"], max_pages=max_pages, max_depth=max_depth,
                snapshot_dir=snapshot_dir,
            )
            site_entry["pages"] = [_page_entry(pg) for pg in pages]
            site_entry["crawl_detect_status"] = "done"
            site_entry["crawl_detect_failure_reason"] = None
        except Exception as e:
            site_entry["crawl_detect_status"] = "failed"
            site_entry["crawl_detect_failure_reason"] = str(e)
        sites_crawled += 1
        save_manifest(manifest_path, manifest)

    # Pass 1b: review every violation not yet reviewed, across all crawled
    # sites, budget-gated before each real call.
    for row in corpus:
        site_entry = manifest["sites"][row["site_id"]]
        if site_entry["crawl_detect_status"] != "done":
            continue

        for page_entry in site_entry["pages"]:
            for v_entry in page_entry["violations"]:
                if v_entry["reviewer_status"] == "done":
                    continue

                count = await count_real_calls_today(db)
                if should_stop_for_budget(count, daily_cap, safety_margin_pct):
                    logger.warning(
                        "eval_runner Pass 1: stopped at %s/%s (safety margin %s%%), "
                        "resume by re-running eval_runner.py",
                        count, daily_cap, safety_margin_pct * 100,
                    )
                    manifest["budget_stopped"] = True
                    save_manifest(manifest_path, manifest)
                    return {
                        "sites_crawled": sites_crawled,
                        "violations_reviewed": violations_reviewed,
                        "budget_stopped": True,
                    }

                try:
                    result = await reviewer_node({
                        "violation": {
                            "id": 0,
                            "wcag_rule": v_entry["wcag_rule"],
                            "element_selector": v_entry["element_selector"],
                            "html_snippet": v_entry["html_snippet"],
                            "message": v_entry["message"],
                            "page_url": page_entry["url"],
                        }
                    })
                    reviewer_output = result["reviewer_result"]
                    v_entry["reviewer_status"] = "done"
                    v_entry["confidence_score"] = reviewer_output.confidence_score
                    v_entry["confirmed"] = reviewer_output.confirmed
                    v_entry["failure_reason"] = None
                    v_entry["error_type"] = None
                except Exception as e:
                    v_entry["reviewer_status"] = "failed"
                    v_entry["failure_reason"] = str(e)
                    v_entry["error_type"] = llm_client._classify_error(e)

                violations_reviewed += 1
                save_manifest(manifest_path, manifest)

    manifest["budget_stopped"] = False
    save_manifest(manifest_path, manifest)
    return {
        "sites_crawled": sites_crawled,
        "violations_reviewed": violations_reviewed,
        "budget_stopped": False,
    }


async def _main() -> None:
    async with async_session_factory() as db:
        summary = await run_pass1(db)
    print(json.dumps(summary, indent=2, default=str))
    await dispose_engine()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
