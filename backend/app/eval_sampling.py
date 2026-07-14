"""
eval_sampling.py — stratified sampler over completed Pass 1 violations.

One stratified draw over violations (by wcag_rule x confidence bucket) feeds
both outputs, per the resolved design: sample_pass2.csv is that violation
sample directly (Pass 2's Developer/Verifier needs specific violations).
sample_manual_labeling.csv is the distinct set of *pages* those same sampled
violations belong to — manual labeling needs full-page context so a human
can catch violations the pipeline never flagged (recall), not just judge
already-flagged ones. Two different outputs, one shared stratification.

Run from inside backend/app/ (matching cost_report.py's convention):

    cd backend/app
    python eval_sampling.py --sample-size 40
"""
import argparse
import csv
import json
import random
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
PROGRESS_PASS1_PATH = EVAL_DIR / "progress_pass1.json"
PASS2_SAMPLE_PATH = EVAL_DIR / "sample_pass2.csv"
MANUAL_LABELING_SAMPLE_PATH = EVAL_DIR / "sample_manual_labeling.csv"

# (lo, hi, label) — half-open [lo, hi) except the last bucket, which
# includes 1.0. Overridable per-call, not hardcoded inline in logic below.
CONFIDENCE_BUCKETS: list[tuple[float, float, str]] = [
    (0.0, 0.5, "low"),
    (0.5, 0.8, "mid"),
    (0.8, 1.0, "high"),
]

PASS2_SAMPLE_FIELDS = [
    "site_id", "page_url", "wcag_rule", "element_selector",
    "confidence_score", "confidence_bucket",
]
MANUAL_LABELING_SAMPLE_FIELDS = ["site_id", "page_url", "tier", "sampled_via_wcag_rules"]


def _bucket_label(score: float, buckets: list[tuple[float, float, str]]) -> str:
    for i, (lo, hi, label) in enumerate(buckets):
        is_last = i == len(buckets) - 1
        if lo <= score < hi or (is_last and score <= hi):
            return label
    raise ValueError(f"confidence_score {score!r} not covered by buckets {buckets!r}")


def load_pass1_violations(manifest_path: Path = PROGRESS_PASS1_PATH) -> list[dict]:
    """Flattens progress_pass1.json into violation-level dicts. Only
    reviewer_status=='done' entries — sampling needs a real confidence_score."""
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    violations = []
    for site_id, site in manifest["sites"].items():
        for page in site["pages"]:
            for v in page["violations"]:
                if v["reviewer_status"] != "done":
                    continue
                violations.append({
                    "site_id": site_id,
                    "tier": site["tier"],
                    "page_url": page["url"],
                    "wcag_rule": v["wcag_rule"],
                    "element_selector": v["element_selector"],
                    "confidence_score": v["confidence_score"],
                })
    return violations


def stratified_sample_violations(
    violations: list[dict],
    sample_size: int,
    buckets: list[tuple[float, float, str]] = CONFIDENCE_BUCKETS,
    seed: int | None = None,
) -> list[dict]:
    """Groups violations by (wcag_rule, confidence_bucket), then round-robins
    across strata (in deterministic key order) so no rule/confidence-band
    goes unrepresented up to sample_size. Each stratum is shuffled with `seed`
    for reproducibility. `sample_size` has no default — the caller decides
    explicitly (PLAN.md suggests aiming for a resulting ~15-20 pages via
    pages_from_violation_sample, which this feeds)."""
    rng = random.Random(seed)
    strata: dict[tuple[str, str], list[dict]] = {}
    for v in violations:
        key = (v["wcag_rule"], _bucket_label(v["confidence_score"], buckets))
        strata.setdefault(key, []).append(v)
    for group in strata.values():
        rng.shuffle(group)

    stratum_keys = sorted(strata.keys())
    sample: list[dict] = []
    idx = 0
    while len(sample) < sample_size and any(strata[k] for k in stratum_keys):
        key = stratum_keys[idx % len(stratum_keys)]
        if strata[key]:
            v = dict(strata[key].pop())
            v["confidence_bucket"] = key[1]
            sample.append(v)
        idx += 1
    return sample


def write_pass2_sample(sample: list[dict], path: Path = PASS2_SAMPLE_PATH) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PASS2_SAMPLE_FIELDS)
        writer.writeheader()
        for row in sample:
            writer.writerow({k: row[k] for k in PASS2_SAMPLE_FIELDS})


def pages_from_violation_sample(sample: list[dict]) -> list[dict]:
    """Dedupes the violation sample to its distinct containing pages,
    aggregating which rules triggered each page's inclusion."""
    pages: dict[tuple[str, str], dict] = {}
    for v in sample:
        key = (v["site_id"], v["page_url"])
        entry = pages.setdefault(key, {
            "site_id": v["site_id"], "page_url": v["page_url"],
            "tier": v["tier"], "wcag_rules": set(),
        })
        entry["wcag_rules"].add(v["wcag_rule"])
    return [
        {
            "site_id": entry["site_id"],
            "page_url": entry["page_url"],
            "tier": entry["tier"],
            "sampled_via_wcag_rules": ",".join(sorted(entry["wcag_rules"])),
        }
        for entry in pages.values()
    ]


def write_manual_labeling_sample(pages: list[dict], path: Path = MANUAL_LABELING_SAMPLE_PATH) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANUAL_LABELING_SAMPLE_FIELDS)
        writer.writeheader()
        for row in pages:
            writer.writerow({k: row[k] for k in MANUAL_LABELING_SAMPLE_FIELDS})


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-size", type=int, required=True,
        help="Violation-level stratified sample size. Feeds sample_pass2.csv "
             "directly; sample_manual_labeling.csv is the distinct set of "
             "pages this same sample touches (PLAN.md suggests aiming for a "
             "resulting ~15-20 pages).",
    )
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    violations = load_pass1_violations()
    sample = stratified_sample_violations(violations, args.sample_size, seed=args.seed)
    write_pass2_sample(sample)

    pages = pages_from_violation_sample(sample)
    write_manual_labeling_sample(pages)

    print(f"Wrote {len(sample)} violations to {PASS2_SAMPLE_PATH}")
    print(f"Wrote {len(pages)} distinct pages to {MANUAL_LABELING_SAMPLE_PATH}")


if __name__ == "__main__":
    _main()
