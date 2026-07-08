"""
main.py — FastAPI app: POST /scan (returns scan_id immediately, runs the
crawl+detect+persist pipeline via BackgroundTasks) and GET /scan/{id}
(polling status + structured violations).

Run from inside backend/app/ (not backend/), matching the flat-import
convention crawler.py already uses (`from detector import ...`):

    cd backend/app
    uvicorn main:app --reload --port 8000

BackgroundTasks is in-process and non-durable — see design.md Section 4f
for the documented, accepted limitation (not something this file works
around).
"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crawler import DEFAULT_MAX_DEPTH, DEFAULT_MAX_PAGES, crawl_site
from db import async_session_factory, dispose_engine, get_db, init_engine
from graph import reasoning_graph
from models import (
    Fix,
    FixFailureReason,
    FixVerificationStatus,
    ImpactAssessment,
    Page,
    Scan,
    ScanStatus,
    Site,
    Violation,
    ViolationStatus,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("accessibility_agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_engine()
    yield
    await dispose_engine()


app = FastAPI(title="Accessibility Compliance Agent", lifespan=lifespan)


class ScanRequest(BaseModel):
    url: str
    max_pages: int = DEFAULT_MAX_PAGES
    max_depth: int = DEFAULT_MAX_DEPTH


class ScanCreateResponse(BaseModel):
    scan_id: int
    status: ScanStatus


class ImpactAssessmentOut(BaseModel):
    id: int
    is_critical_path: bool
    business_risk_score: float | None
    reasoning_text: str | None

    model_config = {"from_attributes": True}


class FixOut(BaseModel):
    id: int
    proposed_code_diff: str | None
    target_selector: str | None
    verification_status: FixVerificationStatus | None
    failure_reason: FixFailureReason | None
    retry_count: int

    model_config = {"from_attributes": True}


class ViolationOut(BaseModel):
    id: int
    wcag_rule: str
    element_selector: str
    severity: str
    confidence: float | None
    status: ViolationStatus
    html_snippet: str | None
    message: str | None
    # "confirmed" / "needs_review" (Phase 2.6) / None for rows written
    # before this column existed — see models.py.
    detection_confidence: str | None
    # Phase 2: populated once the reasoning pass completes for this
    # violation; null if reasoning hasn't run yet or failed (see run_scan's
    # per-violation error handling — a failure leaves these unset, not
    # partially set).
    impact_assessment: ImpactAssessmentOut | None
    fix: FixOut | None

    model_config = {"from_attributes": True}


class PageOut(BaseModel):
    id: int
    url: str
    raw_html_snapshot_path: str | None
    status: str | None
    failure_reason: str | None
    violations: list[ViolationOut]

    model_config = {"from_attributes": True}


class ScanOut(BaseModel):
    id: int
    site_id: int
    status: ScanStatus
    started_at: datetime | None
    completed_at: datetime | None
    pages: list[PageOut]

    model_config = {"from_attributes": True}


@app.post("/scan", response_model=ScanCreateResponse, status_code=202)
async def create_scan(
    req: ScanRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    site = (await db.execute(select(Site).where(Site.url == req.url))).scalar_one_or_none()
    if site is None:
        site = Site(url=req.url)
        db.add(site)
        await db.flush()  # populate site.id before using it below

    scan = Scan(site_id=site.id, status=ScanStatus.queued)
    db.add(scan)
    await db.commit()

    background_tasks.add_task(run_scan, scan.id, req.url, req.max_pages, req.max_depth)
    return ScanCreateResponse(scan_id=scan.id, status=scan.status)


@app.get("/scan/{scan_id}", response_model=ScanOut)
async def get_scan(scan_id: int, db: AsyncSession = Depends(get_db)):
    scan = await db.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return scan


async def run_scan(scan_id: int, url: str, max_pages: int, max_depth: int) -> None:
    """Runs entirely on its own DB session — deliberately never reuses the
    request's injected session. A crawl can run well past 30s (multiple
    Playwright page loads); holding a pooled connection open and idle for
    that whole span would be wasteful and risks the connection being
    reclaimed mid-crawl."""
    async with async_session_factory() as db:
        scan = await db.get(Scan, scan_id)
        scan.status = ScanStatus.running
        scan.started_at = datetime.now(timezone.utc)
        await db.commit()

    try:
        crawled_pages = await crawl_site(url, max_pages=max_pages, max_depth=max_depth)
    except Exception:
        # Catches what crawl_site's own internal per-page try/except can't —
        # e.g. a Playwright browser-launch failure before any page is even
        # attempted. Without this, the scan would hang at "running" forever.
        logger.exception("scan %s failed before any page was crawled", scan_id)
        async with async_session_factory() as db:
            scan = await db.get(Scan, scan_id)
            scan.status = ScanStatus.failed
            scan.completed_at = datetime.now(timezone.utc)
            await db.commit()
        return

    violations_for_reasoning: list[dict] = []

    async with async_session_factory() as db:
        for pg in crawled_pages:
            # Every crawled page gets a row now — loaded or failed — so
            # Phase 4's dashboard can compute a real scan-success-rate from
            # actual logged rows (see models.py module docstring / decision
            # #3). Failed pages still get logged too, for anyone tailing
            # server output live.
            if pg.status != "loaded":
                logger.warning(
                    "scan=%s skipped page url=%s depth=%s failure_reason=%s",
                    scan_id, pg.url, pg.depth, pg.failure_reason,
                )

            page_row = Page(
                scan_id=scan_id,
                url=pg.url,
                raw_html_snapshot_path=pg.snapshot_path,
                status=pg.status,
                failure_reason=pg.failure_reason,
            )
            db.add(page_row)
            await db.flush()  # need page_row.id for the FK below

            if pg.detection_error:
                logger.warning(
                    "scan=%s page url=%s loaded but detection failed: %s",
                    scan_id, pg.url, pg.detection_error,
                )

            for v in pg.violations:
                violation_row = Violation(
                    page_id=page_row.id,
                    wcag_rule=v.wcag_rule,
                    element_selector=v.element_selector,
                    severity=v.severity,
                    status=ViolationStatus.open,
                    html_snippet=v.html_snippet,
                    message=v.message,
                    detection_confidence=v.detection_confidence,
                )
                db.add(violation_row)
                await db.flush()  # need violation_row.id for the reasoning pass below
                violations_for_reasoning.append({
                    "id": violation_row.id,
                    "wcag_rule": violation_row.wcag_rule,
                    "element_selector": violation_row.element_selector,
                    "html_snippet": violation_row.html_snippet or "",
                    "message": violation_row.message or "",
                    "page_url": page_row.url,
                })

        await db.commit()

    # Phase 2 reasoning pass: run the 4-node LangGraph sequentially, one
    # violation at a time — matches Groq's free-tier rate limits and this
    # project's hardware/quota constraints (see design.md). Each violation
    # gets its own DB session and exactly one commit, reached only if the
    # full graph succeeds; a failure at any node propagates out of
    # `ainvoke()` before anything is written for that violation (see
    # graph.py / llm_client.py module docstrings — no partial state is
    # possible by construction, not convention).
    for v in violations_for_reasoning:
        try:
            final_state = await reasoning_graph.ainvoke({"violation": v})
        except Exception as e:
            logger.warning("scan=%s violation=%s reasoning failed: %s", scan_id, v["id"], e)
            continue

        reviewer_result = final_state["reviewer_result"]
        impact_result = final_state["impact_result"]
        developer_result = final_state["developer_result"]

        async with async_session_factory() as db:
            violation_row = await db.get(Violation, v["id"])
            violation_row.confidence = reviewer_result.confidence_score
            db.add(ImpactAssessment(
                violation_id=v["id"],
                is_critical_path=impact_result.is_critical_path,
                reasoning_text=impact_result.reasoning_text,
                business_risk_score=impact_result.business_risk_score,
            ))
            db.add(Fix(
                violation_id=v["id"],
                proposed_code_diff=developer_result.proposed_code_diff,
                target_selector=developer_result.target_selector,
                verification_status=None,
                retry_count=0,
            ))
            await db.commit()

    async with async_session_factory() as db:
        scan = await db.get(Scan, scan_id)
        scan.status = ScanStatus.done
        scan.completed_at = datetime.now(timezone.utc)
        site = await db.get(Site, scan.site_id)
        site.last_scanned_at = scan.completed_at
        await db.commit()
