"""
test_sampling.py — Phase 5 coverage for eval_sampling.py's stratified
sampler. Pure functions over synthetic in-memory violation lists, no DB,
no files, no real Pass 1 data needed.
"""
import eval_sampling


def _make_violations():
    rules = ["image-alt", "color-contrast"]
    bucket_scores = {"low": 0.2, "mid": 0.65, "high": 0.95}
    violations = []
    i = 0
    for rule in rules:
        for bucket, score in bucket_scores.items():
            for j in range(3):
                i += 1
                violations.append({
                    "site_id": "1",
                    "tier": "low",
                    "page_url": f"http://site-a.test/page-{i}.html",
                    "wcag_rule": rule,
                    "element_selector": f"#{rule}-{bucket}-{j}",
                    "confidence_score": score,
                })
    return violations


def test_bucket_label_boundaries():
    buckets = eval_sampling.CONFIDENCE_BUCKETS
    assert eval_sampling._bucket_label(0.0, buckets) == "low"
    assert eval_sampling._bucket_label(0.49, buckets) == "low"
    assert eval_sampling._bucket_label(0.5, buckets) == "mid"
    assert eval_sampling._bucket_label(0.79, buckets) == "mid"
    assert eval_sampling._bucket_label(0.8, buckets) == "high"
    assert eval_sampling._bucket_label(1.0, buckets) == "high"


def test_stratified_sample_covers_every_rule_bucket_combo():
    violations = _make_violations()
    # 2 rules x 3 buckets = 6 strata, 3 violations each (18 total).
    sample = eval_sampling.stratified_sample_violations(violations, sample_size=6, seed=42)

    assert len(sample) == 6
    seen_strata = {(v["wcag_rule"], v["confidence_bucket"]) for v in sample}
    assert seen_strata == {
        ("image-alt", "low"), ("image-alt", "mid"), ("image-alt", "high"),
        ("color-contrast", "low"), ("color-contrast", "mid"), ("color-contrast", "high"),
    }


def test_stratified_sample_deterministic_given_seed():
    violations = _make_violations()
    sample1 = eval_sampling.stratified_sample_violations(violations, sample_size=6, seed=7)
    sample2 = eval_sampling.stratified_sample_violations(violations, sample_size=6, seed=7)
    assert [v["element_selector"] for v in sample1] == [v["element_selector"] for v in sample2]


def test_stratified_sample_caps_at_available_violations():
    violations = _make_violations()
    sample = eval_sampling.stratified_sample_violations(violations, sample_size=1000, seed=1)
    assert len(sample) == len(violations)


def test_pages_from_violation_sample_dedupes_and_aggregates_rules():
    sample = [
        {"site_id": "1", "page_url": "http://a.test/x.html", "tier": "low",
         "wcag_rule": "image-alt", "element_selector": "#a", "confidence_score": 0.9,
         "confidence_bucket": "high"},
        {"site_id": "1", "page_url": "http://a.test/x.html", "tier": "low",
         "wcag_rule": "color-contrast", "element_selector": "#b", "confidence_score": 0.3,
         "confidence_bucket": "low"},
        {"site_id": "2", "page_url": "http://b.test/y.html", "tier": "high",
         "wcag_rule": "image-alt", "element_selector": "#c", "confidence_score": 0.9,
         "confidence_bucket": "high"},
    ]
    pages = eval_sampling.pages_from_violation_sample(sample)

    assert len(pages) == 2
    page_a = next(p for p in pages if p["page_url"] == "http://a.test/x.html")
    assert page_a["site_id"] == "1"
    assert page_a["tier"] == "low"
    assert page_a["sampled_via_wcag_rules"] == "color-contrast,image-alt"

    page_b = next(p for p in pages if p["page_url"] == "http://b.test/y.html")
    assert page_b["sampled_via_wcag_rules"] == "image-alt"
