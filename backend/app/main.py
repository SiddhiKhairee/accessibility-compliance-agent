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
import hashlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

import cost_report
import page_fixer
from config import settings
from crawler import DEFAULT_MAX_DEPTH, DEFAULT_MAX_PAGES, SNAPSHOT_DIR, crawl_site
from db import async_session_factory, dispose_engine, get_db, init_engine
from graph import reasoning_graph
from models import (
    Approval,
    ApprovalDecision,
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    # Not a Fix model attribute (Approval has no relationship() defined on
    # Fix — see models.py's own note inviting Phase 3/4 to add one when
    # actually needed). Defaults to None here so ScanOut.model_validate()
    # doesn't error on the missing attribute; get_scan below fills in the
    # real value afterward via a separate query. Needed so the Review &
    # Approve tab doesn't lose track of prior approve/reject decisions on
    # a page refresh.
    latest_approval_decision: ApprovalDecision | None = None

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
    # Phase 4: page_fixer.py's combine-and-reverify output — see
    # POST /pages/{id}/generate-fixed-page.
    fixed_html_snapshot_path: str | None
    combined_verification_status: str | None
    combined_verification_detail: str | None
    combined_verified_at: datetime | None

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

    scan_out = ScanOut.model_validate(scan)

    fix_ids = [
        v.fix.id for page in scan_out.pages for v in page.violations if v.fix is not None
    ]
    if fix_ids:
        approval_rows = (await db.execute(
            select(Approval).where(Approval.fix_id.in_(fix_ids)).order_by(Approval.fix_id, desc(Approval.id))
        )).scalars().all()
        latest_by_fix: dict[int, Approval] = {}
        for a in approval_rows:
            latest_by_fix.setdefault(a.fix_id, a)
        for page in scan_out.pages:
            for v in page.violations:
                if v.fix is not None and v.fix.id in latest_by_fix:
                    v.fix.latest_approval_decision = latest_by_fix[v.fix.id].decision

    return scan_out


class SiteOut(BaseModel):
    id: int
    url: str
    last_scanned_at: datetime | None
    latest_scan_status: ScanStatus | None

    model_config = {"from_attributes": True}


class ScanSummaryOut(BaseModel):
    """Deliberately lighter than ScanOut — no `pages` — for listing many
    scans at once. Scan.pages' lazy="selectin" relationship still triggers
    on load regardless (see module docstring below for why that's left
    alone rather than reworked), but this model just never serializes it."""

    id: int
    site_id: int
    status: ScanStatus
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


@app.get("/sites", response_model=list[SiteOut])
async def list_sites(db: AsyncSession = Depends(get_db)):
    """Avoids Site.scans (no lazy strategy declared, would need an explicit
    selectinload) and definitely avoids Scan.pages' lazy="selectin" cascade
    (which would recursively pull every page/violation/fix for every scan
    just to show a site list) — a plain aggregate query for "latest scan
    per site" instead, joined back onto Site."""
    latest_scan_subq = (
        select(Scan.site_id, func.max(Scan.id).label("latest_scan_id"))
        .group_by(Scan.site_id)
        .subquery()
    )
    rows = (await db.execute(
        select(Site, Scan.status)
        .join(latest_scan_subq, latest_scan_subq.c.site_id == Site.id, isouter=True)
        .join(Scan, Scan.id == latest_scan_subq.c.latest_scan_id, isouter=True)
        .order_by(Site.id)
    )).all()
    return [
        SiteOut(id=site.id, url=site.url, last_scanned_at=site.last_scanned_at, latest_scan_status=status)
        for site, status in rows
    ]


@app.get("/scans", response_model=list[ScanSummaryOut])
async def list_scans(site_id: int | None = None, db: AsyncSession = Depends(get_db)):
    query = select(Scan).order_by(desc(Scan.id))
    if site_id is not None:
        query = query.where(Scan.site_id == site_id)
    scans = (await db.execute(query)).scalars().all()
    return scans


class ApprovalRequest(BaseModel):
    decision: ApprovalDecision
    approver: str


class ApprovalOut(BaseModel):
    id: int
    fix_id: int
    approver: str | None
    decision: ApprovalDecision | None
    decided_at: datetime | None

    model_config = {"from_attributes": True}


@app.post("/fixes/{fix_id}/approval", response_model=ApprovalOut, status_code=201)
async def create_approval(fix_id: int, req: ApprovalRequest, db: AsyncSession = Depends(get_db)):
    """Always inserts a new Approval row rather than updating one in place —
    a human can change their mind later, and the most recent row per fix_id
    is what generate-fixed-page (below) treats as authoritative. Restricted
    to verified fixes: approving/rejecting a fix that never passed
    verification (rejected/manual_review/still pending) has nothing
    trustworthy to approve."""
    fix = await db.get(Fix, fix_id)
    if fix is None:
        raise HTTPException(status_code=404, detail="fix not found")
    if fix.verification_status != FixVerificationStatus.verified:
        raise HTTPException(
            status_code=400,
            detail=f"fix {fix_id} is not verified (status={fix.verification_status}); only verified fixes can be approved/rejected",
        )

    approval = Approval(
        fix_id=fix_id, approver=req.approver, decision=req.decision,
        decided_at=datetime.now(timezone.utc),
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)
    return approval


class GenerateFixedPageResponse(BaseModel):
    page_id: int
    status: str  # "clean" | "violations_remain" | "error"
    detail: str
    fixes_included_count: int
    fixes_pending_count: int
    download_available: bool


@app.post("/pages/{page_id}/generate-fixed-page", response_model=GenerateFixedPageResponse)
async def generate_fixed_page(page_id: int, db: AsyncSession = Depends(get_db)):
    """Partial approval is allowed, explicitly: whatever is approved at
    call time gets combined, and the response always reports exactly how
    many of the page's verified fixes were included vs not — never silent
    about a partial result. Requires at least one approved fix to exist.

    Runs synchronously (not BackgroundTasks) — scoped to one page's
    violations, not a whole site crawl, so it doesn't need POST /scan's
    async pattern.
    """
    page = await db.get(Page, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    if page.status != "loaded" or page.raw_html_snapshot_path is None:
        raise HTTPException(
            status_code=400,
            detail="page has no raw HTML snapshot to combine fixes onto (status != 'loaded')",
        )

    violations = (await db.execute(
        select(Violation).where(Violation.page_id == page_id)
    )).scalars().all()
    baseline = [{"wcag_rule": v.wcag_rule, "element_selector": v.element_selector} for v in violations]

    verified_violations = [v for v in violations if v.fix is not None and v.fix.verification_status == FixVerificationStatus.verified]
    total_fixes_count = len(verified_violations)
    fix_ids = [v.fix.id for v in verified_violations]

    latest_approval_by_fix: dict[int, Approval] = {}
    if fix_ids:
        approval_rows = (await db.execute(
            select(Approval).where(Approval.fix_id.in_(fix_ids)).order_by(Approval.fix_id, desc(Approval.id))
        )).scalars().all()
        for a in approval_rows:
            latest_approval_by_fix.setdefault(a.fix_id, a)

    approved_violations = [
        v for v in verified_violations
        if latest_approval_by_fix.get(v.fix.id) is not None
        and latest_approval_by_fix[v.fix.id].decision == ApprovalDecision.approved
    ]
    fixes_included_count = len(approved_violations)
    fixes_pending_count = total_fixes_count - fixes_included_count

    if fixes_included_count == 0:
        raise HTTPException(status_code=400, detail="no approved fixes on this page to generate")

    fixes_to_apply = [
        page_fixer.FixToApply(
            wcag_rule=v.wcag_rule,
            element_selector=v.element_selector,
            target_selector=v.fix.target_selector,
            proposed_code_diff=v.fix.proposed_code_diff,
        )
        for v in approved_violations
    ]

    result = await page_fixer.apply_verified_fixes_to_page(
        page_url=page.url,
        raw_html_snapshot_path=page.raw_html_snapshot_path,
        fixes=fixes_to_apply,
        baseline=baseline,
    )

    combined_detail = f"{fixes_included_count}/{total_fixes_count} violations addressed; {result.detail}"

    page.combined_verification_status = result.status
    page.combined_verification_detail = combined_detail
    page.combined_verified_at = datetime.now(timezone.utc)
    if result.status == "clean" and result.fixed_html is not None:
        # SNAPSHOT_DIR is only ever created by crawler.py's crawl_site()
        # (mkdir(parents=True, exist_ok=True)) — a fresh checkout that
        # never ran a real scan (e.g. CI, which builds this state directly
        # via fixture rows) has no data/raw_html/ directory at all yet.
        # Real bug caught by CI, not local dev: this machine already had
        # the directory from prior real scans, masking it.
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        filename = hashlib.sha256(f"fixed:{page.id}".encode()).hexdigest()[:16] + ".html"
        fixed_path = SNAPSHOT_DIR / filename
        fixed_path.write_text(result.fixed_html, encoding="utf-8")
        page.fixed_html_snapshot_path = str(fixed_path)
    await db.commit()

    return GenerateFixedPageResponse(
        page_id=page_id,
        status=result.status,
        detail=combined_detail,
        fixes_included_count=fixes_included_count,
        fixes_pending_count=fixes_pending_count,
        download_available=result.status == "clean",
    )


@app.get("/pages/{page_id}/download-fixed")
async def download_fixed_page(page_id: int, db: AsyncSession = Depends(get_db)):
    page = await db.get(Page, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    if page.combined_verification_status != "clean" or page.fixed_html_snapshot_path is None:
        raise HTTPException(status_code=404, detail="no clean fixed page available for this page")
    return FileResponse(
        page.fixed_html_snapshot_path, media_type="text/html",
        filename=f"page_{page_id}_fixed.html",
    )


@app.get("/performance/summary")
async def get_performance_summary(site_id: int | None = None, db: AsyncSession = Depends(get_db)):
    """Wraps cost_report.py's query functions — no metric logic duplicated
    here. `pr_metrics` is explicitly None: Phase 4 deliberately doesn't open
    real GitHub PRs (see design.md's Phase 4 section), so there's nothing
    real to report yet — an honest placeholder, not a silently missing
    field, so the dashboard can render "N/A" rather than guessing why the
    key is absent."""
    return {
        "agent_cost_summary": await cost_report.compute_agent_cost_summary(db),
        "scan_performance_summary": await cost_report.compute_scan_performance_summary(db),
        "accessibility_score_trend": await cost_report.compute_accessibility_score_trend(db, site_id=site_id),
        "pr_metrics": None,
    }


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

            # The full pre-fix violation set for this page — threaded into
            # the graph state so the Verifier can diff its post-fix rerun
            # against it without any node touching the DB (see graph.py's
            # module docstring). Built once per page from data already in
            # memory (crawl_site's own detection pass), not re-queried.
            baseline_for_page = [
                {"wcag_rule": v.wcag_rule, "element_selector": v.element_selector}
                for v in pg.violations
            ]

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
                    "violation": {
                        "id": violation_row.id,
                        "wcag_rule": violation_row.wcag_rule,
                        "element_selector": violation_row.element_selector,
                        "html_snippet": violation_row.html_snippet or "",
                        "message": violation_row.message or "",
                        "page_url": page_row.url,
                    },
                    "baseline_violations": baseline_for_page,
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
    for entry in violations_for_reasoning:
        v = entry["violation"]
        try:
            final_state = await reasoning_graph.ainvoke(entry)
        except Exception as e:
            logger.warning("scan=%s violation=%s reasoning failed: %s", scan_id, v["id"], e)
            continue

        reviewer_result = final_state["reviewer_result"]
        impact_result = final_state["impact_result"]
        developer_result = final_state["developer_result"]
        verifier_result = final_state["verifier_result"]

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
                verification_status=verifier_result.verification_status,
                failure_reason=verifier_result.failure_reason,
                retry_count=verifier_result.retry_count,
                # Stamped whenever the verifier reaches any terminal verdict
                # (verified/rejected/manual_review alike), not only on a
                # positive result — matches this file's own
                # Scan.completed_at convention (set on success or failure).
                verified_at=datetime.now(timezone.utc),
            ))
            await db.commit()

    async with async_session_factory() as db:
        scan = await db.get(Scan, scan_id)
        scan.status = ScanStatus.done
        scan.completed_at = datetime.now(timezone.utc)
        site = await db.get(Site, scan.site_id)
        site.last_scanned_at = scan.completed_at
        await db.commit()
