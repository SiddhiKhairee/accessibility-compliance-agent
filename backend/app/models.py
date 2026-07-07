"""
models.py — async SQLAlchemy ORM models for all 8 tables in docs/schema.md.

All 8 tables are created in one initial migration even though Phase 1 only
populates sites/scans/pages/violations — schema.md is locked up front, so
later phases (Reviewer/Impact/Developer/Verifier agents, approvals, LLM call
logging) just write to already-existing tables rather than re-migrating the
base schema.

Two deliberate additions beyond schema.md's literal column list (see
docs/schema.md's own inline comments for the same rationale, kept in sync
here):
  - `pages.status` / `pages.failure_reason`: every crawled page gets a row
    now, loaded or failed, so Phase 4's dashboard can compute a real
    scan-success-rate and Phase 5's evaluation numbers are traceable to
    actual logged rows instead of only-ever-seeing the pages that succeeded.
  - `violations.html_snippet` / `violations.message`: detector.py's
    Violation dataclass already produces both; persisting them means
    Phase 2's Developer Agent gets fix-relevant context directly instead of
    re-deriving it by re-opening the page's raw HTML snapshot and
    re-locating the element by selector.
"""
import enum
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# All datetime columns use timezone=True (Postgres `timestamptz`) and store
# UTC-aware values (main.py uses datetime.now(timezone.utc) throughout).
# Without this, asyncpg raises "can't subtract offset-naive and
# offset-aware datetimes" the moment a tz-aware Python datetime is bound to
# a plain `timestamp without time zone` column — hit and fixed during Phase
# 1 verification (see PHASE1_COMPLETION_REPORT.md).
_TZ_DATETIME = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


def _enum(py_enum: type[enum.Enum], name: str) -> SAEnum:
    # values_callable stores the enum's .value in Postgres, not its .name —
    # explicit rather than relying on name==value coincidentally matching.
    return SAEnum(py_enum, name=name, values_callable=lambda e: [m.value for m in e])


class ScanStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class ViolationStatus(str, enum.Enum):
    open = "open"
    fixed = "fixed"
    rejected = "rejected"


class FixVerificationStatus(str, enum.Enum):
    verified = "verified"
    rejected = "rejected"
    manual_review = "manual_review"


class FixFailureReason(str, enum.Enum):
    invalid_html = "invalid_html"
    dom_changed = "dom_changed"
    playwright_timeout = "playwright_timeout"
    diff_failed_to_apply = "diff_failed_to_apply"


class ApprovalDecision(str, enum.Enum):
    approved = "approved"
    rejected = "rejected"


class PrStatus(str, enum.Enum):
    created = "created"
    merged = "merged"
    rejected = "rejected"
    pending = "pending"


class AgentName(str, enum.Enum):
    Reviewer = "Reviewer"
    Impact = "Impact"
    Developer = "Developer"
    Verifier = "Verifier"


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, index=True, nullable=False)
    last_scanned_at: Mapped[datetime | None] = mapped_column(_TZ_DATETIME, nullable=True)

    scans: Mapped[list["Scan"]] = relationship(back_populates="site")


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False)
    status: Mapped[ScanStatus] = mapped_column(
        _enum(ScanStatus, "scan_status"), nullable=False, default=ScanStatus.queued
    )
    started_at: Mapped[datetime | None] = mapped_column(_TZ_DATETIME, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(_TZ_DATETIME, nullable=True)

    site: Mapped["Site"] = relationship(back_populates="scans")
    pages: Mapped[list["Page"]] = relationship(
        back_populates="scan", lazy="selectin", cascade="all, delete-orphan"
    )


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id"), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    raw_html_snapshot_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Nullable: a failed/skipped page (status="failed") never gets a
    # snapshot written (crawler.py only writes one after a successful
    # page.goto()), so this can't be NOT NULL now that every crawled page —
    # loaded or failed — gets a row (see module docstring).
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Added beyond schema.md's literal column list — see module docstring.
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Added beyond schema.md's literal column list — see module docstring.

    scan: Mapped["Scan"] = relationship(back_populates="pages")
    violations: Mapped[list["Violation"]] = relationship(
        back_populates="page", lazy="selectin", cascade="all, delete-orphan"
    )


class Violation(Base):
    __tablename__ = "violations"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id"), nullable=False)
    wcag_rule: Mapped[str] = mapped_column(String(100), nullable=False)
    element_selector: Mapped[str] = mapped_column(Text, nullable=False)
    # `severity` is deliberately a plain String, not an enum: schema.md gives
    # it no closed value list, and detector.py's Violation.severity can
    # already emit "unknown" (when axe's `impact` is None), which isn't one
    # of axe's 4 canonical values — locking it to a Postgres enum risks a
    # migration/insert failure the first time axe returns something
    # unexpected.
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # Phase 2's Reviewer Agent populates this
    status: Mapped[ViolationStatus] = mapped_column(
        _enum(ViolationStatus, "violation_status"), nullable=False, default=ViolationStatus.open
    )
    html_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Added beyond schema.md's literal column list — see module docstring.
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Added beyond schema.md's literal column list — see module docstring.

    page: Mapped["Page"] = relationship(back_populates="violations")
    # Phase 2: added now that main.py's run_scan actually queries through
    # these (GET /scan/{id} needs to surface confidence/impact/fix per
    # violation). uselist=False since each scan produces fresh Violation
    # rows (the crawler re-crawls from scratch every scan), so a violation
    # gets at most one impact_assessment/fix in this design — no unique DB
    # constraint added for this, so two rows existing would surface as a
    # loud SQLAlchemy error rather than silently picking one.
    impact_assessment: Mapped["ImpactAssessment | None"] = relationship(
        back_populates="violation", uselist=False, lazy="selectin"
    )
    fix: Mapped["Fix | None"] = relationship(back_populates="violation", uselist=False, lazy="selectin")


# approvals / llm_call_logs: FK columns only, no relationship() defined —
# nothing queries through them yet. Phase 3/4 authors should pick their own
# loading strategy when they actually need one.


class ImpactAssessment(Base):
    __tablename__ = "impact_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    violation_id: Mapped[int] = mapped_column(ForeignKey("violations.id"), nullable=False)
    is_critical_path: Mapped[bool] = mapped_column(nullable=False, default=False)
    reasoning_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    violation: Mapped["Violation"] = relationship(back_populates="impact_assessment")


class Fix(Base):
    __tablename__ = "fixes"

    id: Mapped[int] = mapped_column(primary_key=True)
    violation_id: Mapped[int] = mapped_column(ForeignKey("violations.id"), nullable=False)
    proposed_code_diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_selector: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_status: Mapped[FixVerificationStatus | None] = mapped_column(
        _enum(FixVerificationStatus, "fix_verification_status"), nullable=True
    )
    failure_reason: Mapped[FixFailureReason | None] = mapped_column(
        _enum(FixFailureReason, "fix_failure_reason"), nullable=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verified_at: Mapped[datetime | None] = mapped_column(_TZ_DATETIME, nullable=True)

    violation: Mapped["Violation"] = relationship(back_populates="fix")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    fix_id: Mapped[int] = mapped_column(ForeignKey("fixes.id"), nullable=False)
    approver: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decision: Mapped[ApprovalDecision | None] = mapped_column(
        _enum(ApprovalDecision, "approval_decision"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(_TZ_DATETIME, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    pr_status: Mapped[PrStatus | None] = mapped_column(_enum(PrStatus, "pr_status"), nullable=True)


class LlmCallLog(Base):
    __tablename__ = "llm_call_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_name: Mapped[AgentName] = mapped_column(_enum(AgentName, "agent_name"), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False)
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    cache_hit: Mapped[bool] = mapped_column(nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ_DATETIME, nullable=False)
    # Added beyond schema.md's literal column list, Phase 2 — see
    # llm_client.py module docstring for why is_mock is a dedicated column
    # rather than an overloaded model_used sentinel value.
    is_mock: Mapped[bool] = mapped_column(nullable=False, default=False)
    # Full exception type + message + a raw-response snippet, capped at
    # 8000 chars in llm_client.py before insert (Text has no real storage
    # cost; the cap just guards against a pathological runaway response).
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Small controlled vocabulary (timeout/rate_limited/http_error/
    # json_decode_error/validation_error/unknown) kept separate from
    # `error` so failure-rate analysis is a clean categorical filter, not
    # string-parsing exception names out of free text.
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)


class LlmResponseCache(Base):
    __tablename__ = "llm_response_cache"

    # Reviewer-agent-only persistent cache (Phase 2 scope). Not used for
    # Impact/Developer — see llm_client.py module docstring: Developer's
    # output carries an instance-specific target_selector unsafe to reuse
    # across violations, and Impact's LLM-fallback reasons about the page
    # URL, not the violating element, so this key shape doesn't apply to
    # it. Both are deferred to Phase 3's real cost-optimization scope.
    id: Mapped[int] = mapped_column(primary_key=True)
    wcag_rule: Mapped[str] = mapped_column(String(100), nullable=False)
    # sha256("Reviewer" + wcag_rule + normalized_html_snippet)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TZ_DATETIME, nullable=False)
