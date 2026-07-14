"""
eval_report.py — Phase 5 EVALUATION.md metric computation. Skeleton only:
real signatures and docstrings describing the intended calculation, no real
logic yet (needs actual Pass 1/Pass 2 data and hand-filled manual_labels.csv/
fix_spotcheck.csv, none of which exist yet). Fills in once that data exists.

Run from inside backend/app/ (matching cost_report.py's convention):

    cd backend/app
    python eval_report.py
"""
import asyncio
import json
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from db import async_session_factory, dispose_engine

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
PROGRESS_PASS1_PATH = EVAL_DIR / "progress_pass1.json"
MANUAL_LABELS_PATH = EVAL_DIR / "manual_labels.csv"
FIX_SPOTCHECK_PATH = EVAL_DIR / "fix_spotcheck.csv"


def compute_precision_recall_fp_rate(manual_labels_path: Path = MANUAL_LABELS_PATH) -> dict:
    """Reads manual_labels.csv. Precision = correct / (correct +
    false_positive) among pipeline_flagged=true rows. False-positive rate =
    false_positive / pipeline_flagged=true rows. Recall = correct /
    (correct + missed), where 'missed' rows are the ones you hand-add for
    violations the pipeline never flagged (pipeline_flagged=false) — that's
    the whole reason the CSV schema carries pipeline_flagged rather than
    only ever containing pipeline-sourced rows.
    """
    raise NotImplementedError("needs real manual_labels.csv data from a completed Phase 5 labeling pass")


def compute_false_verification_rate(fix_spotcheck_path: Path = FIX_SPOTCHECK_PATH) -> dict:
    """Reads fix_spotcheck.csv. False verification rate = rows where
    verification_status=='verified' but human_label disagrees, divided by
    total spot-checked 'verified' rows.
    """
    raise NotImplementedError("needs real fix_spotcheck.csv data from a completed Phase 5 spot-check pass")


async def compute_confidence_calibration(
    db: AsyncSession, manual_labels_path: Path = MANUAL_LABELS_PATH,
) -> dict:
    """Reviewer confidence_score (from manual_labels.csv's
    reviewer_confidence_score column) vs. actual outcome (human_label),
    bucketed the same way eval_sampling.CONFIDENCE_BUCKETS does, filtered to
    cache_hit=false llm_call_logs rows only per the Phase 2 guardrail
    (design.md Section 9 / PLAN.md Phase 5) — a cached judgment reused
    across pages would understate real variance and bias calibration
    numbers toward looking artificially consistent.
    """
    raise NotImplementedError("needs real manual_labels.csv data + llm_call_logs from a completed Pass 1 run")


def compute_per_rule_failure_rates(manifest_path: Path = PROGRESS_PASS1_PATH) -> dict:
    """Reads progress_pass1.json, not llm_call_logs — llm_call_logs has no
    wcag_rule column (it's a per-agent-call log, not violation-scoped), so
    per-rule error_type failure rate has to come from the manifest's own
    per-violation reviewer_status/error_type fields, grouped by wcag_rule.
    """
    raise NotImplementedError("needs a real (non-empty) progress_pass1.json from a completed Pass 1 run")


async def generate_report(db: AsyncSession) -> dict:
    """Orchestrates the four compute_* functions above into the shape
    EVALUATION.md's sections expect. Real implementation once Pass 1/Pass 2
    have actually run and manual_labels.csv/fix_spotcheck.csv are filled in.
    """
    return {
        "precision_recall_fp_rate": compute_precision_recall_fp_rate(),
        "false_verification_rate": compute_false_verification_rate(),
        "confidence_calibration": await compute_confidence_calibration(db),
        "per_rule_failure_rates": compute_per_rule_failure_rates(),
    }


async def _main() -> None:
    async with async_session_factory() as db:
        report = await generate_report(db)
    print(json.dumps(report, indent=2, default=str))
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(_main())
