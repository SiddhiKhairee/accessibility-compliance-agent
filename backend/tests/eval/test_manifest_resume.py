"""
test_manifest_resume.py — Phase 5 coverage for eval_runner.py's resumable
manifest and Pass 1 orchestration. No real Groq calls or real crawling:
crawler.crawl_site and eval_runner.reviewer_node (the graph.reviewer_node
name eval_runner imported directly) are monkeypatched, matching the
"isolate the one seam" pattern test_llm_client_cache.py already uses for
_make_paced_request.
"""
import json

import crawler
import eval_runner
import pytest
from agents.reviewer.schema import ReviewerOutput
from db import async_session_factory

FAKE_CORPUS = [
    {"site_id": "1", "url": "http://site-a.test", "tier": "low"},
    {"site_id": "2", "url": "http://site-b.test", "tier": "high"},
]


def _write_corpus_csv(path, corpus=FAKE_CORPUS):
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("site_id,url,tier\n")
        for row in corpus:
            f.write(f"{row['site_id']},{row['url']},{row['tier']}\n")
    return path


def test_load_or_init_manifest_creates_from_corpus(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest = eval_runner.load_or_init_manifest(manifest_path, FAKE_CORPUS)

    assert set(manifest["sites"].keys()) == {"1", "2"}
    for site_id, row in zip(["1", "2"], FAKE_CORPUS):
        entry = manifest["sites"][site_id]
        assert entry["url"] == row["url"]
        assert entry["tier"] == row["tier"]
        assert entry["crawl_detect_status"] == "pending"
        assert entry["pages"] == []


def test_load_or_init_manifest_loads_existing_without_resetting(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    seeded = eval_runner.load_or_init_manifest(manifest_path, FAKE_CORPUS)
    seeded["sites"]["1"]["crawl_detect_status"] = "done"
    seeded["sites"]["1"]["pages"] = [{"url": "http://site-a.test/", "load_status": "loaded",
                                       "load_failure_reason": None, "snapshot_path": None, "violations": []}]
    eval_runner.save_manifest(manifest_path, seeded)

    reloaded = eval_runner.load_or_init_manifest(manifest_path, FAKE_CORPUS)
    assert reloaded["sites"]["1"]["crawl_detect_status"] == "done"
    assert len(reloaded["sites"]["1"]["pages"]) == 1
    assert reloaded["sites"]["2"]["crawl_detect_status"] == "pending"


async def test_run_pass1_skips_already_done_sites(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "false")
    corpus_path = _write_corpus_csv(tmp_path / "corpus.csv", FAKE_CORPUS[:1])
    manifest_path = tmp_path / "manifest.json"

    seeded = eval_runner.load_or_init_manifest(manifest_path, FAKE_CORPUS[:1])
    seeded["sites"]["1"]["crawl_detect_status"] = "done"
    eval_runner.save_manifest(manifest_path, seeded)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("crawl_site should not be called for an already-done site")
    monkeypatch.setattr(crawler, "crawl_site", _fail_if_called)

    async with async_session_factory() as db:
        result = await eval_runner.run_pass1(
            db, corpus_path=corpus_path, manifest_path=manifest_path,
            snapshot_dir=tmp_path / "snapshots",
        )

    assert result["sites_crawled"] == 0
    assert result["budget_stopped"] is False


async def test_run_pass1_stops_cleanly_at_budget_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "false")
    corpus_path = _write_corpus_csv(tmp_path / "corpus.csv", FAKE_CORPUS[:1])
    manifest_path = tmp_path / "manifest.json"

    violation = crawler.Violation(
        wcag_rule="image-alt", element_selector="img.hero", severity="serious",
        html_snippet="<img class='hero'>", message="missing alt text",
    )
    page = crawler.CrawledPage(
        url="http://site-a.test/", depth=0, status="loaded",
        title="Site A", snapshot_path="/tmp/fake.html", violations=[violation],
    )

    async def _fake_crawl_site(*args, **kwargs):
        return [page]
    monkeypatch.setattr(crawler, "crawl_site", _fake_crawl_site)

    async def _fake_over_budget(db, model=None, now=None):
        return 950
    monkeypatch.setattr(eval_runner, "count_real_calls_today", _fake_over_budget)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("reviewer_node should not be called once the budget guard trips")
    monkeypatch.setattr(eval_runner, "reviewer_node", _fail_if_called)

    async with async_session_factory() as db:
        result = await eval_runner.run_pass1(
            db, corpus_path=corpus_path, manifest_path=manifest_path,
            snapshot_dir=tmp_path / "snapshots", daily_cap=1000, safety_margin_pct=0.9,
        )

    assert result["budget_stopped"] is True
    assert result["violations_reviewed"] == 0

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["budget_stopped"] is True
    saved_violation = manifest["sites"]["1"]["pages"][0]["violations"][0]
    assert saved_violation["reviewer_status"] == "pending"


async def test_run_pass1_resumes_only_pending_violations(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "false")
    corpus_path = _write_corpus_csv(tmp_path / "corpus.csv", FAKE_CORPUS[:1])
    manifest_path = tmp_path / "manifest.json"

    seeded = eval_runner.load_or_init_manifest(manifest_path, FAKE_CORPUS[:1])
    seeded["sites"]["1"]["crawl_detect_status"] = "done"
    seeded["sites"]["1"]["pages"] = [{
        "url": "http://site-a.test/", "load_status": "loaded", "load_failure_reason": None,
        "snapshot_path": None,
        "violations": [
            {"wcag_rule": "image-alt", "element_selector": "img.a", "html_snippet": "<img class='a'>",
             "message": "missing alt", "reviewer_status": "done", "confidence_score": 0.8,
             "confirmed": True, "failure_reason": None, "error_type": None},
            {"wcag_rule": "color-contrast", "element_selector": "p.b", "html_snippet": "<p class='b'>",
             "message": "low contrast", "reviewer_status": "pending", "confidence_score": None,
             "confirmed": None, "failure_reason": None, "error_type": None},
        ],
    }]
    eval_runner.save_manifest(manifest_path, seeded)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("crawl_site should not be called for an already-done site")
    monkeypatch.setattr(crawler, "crawl_site", _fail_if_called)

    async def _fake_under_budget(db, model=None, now=None):
        return 0
    monkeypatch.setattr(eval_runner, "count_real_calls_today", _fake_under_budget)

    call_count = {"n": 0}
    reviewed_selectors = []

    async def _fake_reviewer_node(state):
        call_count["n"] += 1
        reviewed_selectors.append(state["violation"]["element_selector"])
        return {"reviewer_result": ReviewerOutput(confirmed=True, confidence_score=0.7, reasoning="ok")}
    monkeypatch.setattr(eval_runner, "reviewer_node", _fake_reviewer_node)

    async with async_session_factory() as db:
        result = await eval_runner.run_pass1(
            db, corpus_path=corpus_path, manifest_path=manifest_path,
            snapshot_dir=tmp_path / "snapshots",
        )

    assert call_count["n"] == 1
    assert reviewed_selectors == ["p.b"]
    assert result["violations_reviewed"] == 1
    assert result["budget_stopped"] is False

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    violations = manifest["sites"]["1"]["pages"][0]["violations"]
    assert all(v["reviewer_status"] == "done" for v in violations)


async def test_run_pass1_crawls_all_sites_before_reviewing_any(tmp_path, monkeypatch):
    """A violation-heavy site (site 1, 3 violations) must not block site 2
    from being crawled, even when the review budget is already exhausted —
    crawling and Reviewer scoring are two separate sequential passes, not
    interleaved per-site."""
    monkeypatch.setenv("LLM_MOCK", "false")
    corpus_path = _write_corpus_csv(tmp_path / "corpus.csv", FAKE_CORPUS)
    manifest_path = tmp_path / "manifest.json"

    heavy_violations = [
        crawler.Violation(
            wcag_rule="image-alt", element_selector=f"img.{i}", severity="serious",
            html_snippet=f"<img class='{i}'>", message="missing alt text",
        )
        for i in range(3)
    ]
    heavy_page = crawler.CrawledPage(
        url="http://site-a.test/", depth=0, status="loaded",
        title="Site A", snapshot_path="/tmp/fake-a.html", violations=heavy_violations,
    )
    light_page = crawler.CrawledPage(
        url="http://site-b.test/", depth=0, status="loaded",
        title="Site B", snapshot_path="/tmp/fake-b.html", violations=[],
    )

    async def _fake_crawl_site(url, *args, **kwargs):
        return [heavy_page] if url == "http://site-a.test" else [light_page]
    monkeypatch.setattr(crawler, "crawl_site", _fake_crawl_site)

    # Pre-exhausted budget: if review were interleaved with crawl, site 1's
    # violations would trip this guard before site 2 ever got crawled.
    async def _fake_over_budget(db, model=None, now=None):
        return 950
    monkeypatch.setattr(eval_runner, "count_real_calls_today", _fake_over_budget)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("reviewer_node should not be called once the budget guard trips")
    monkeypatch.setattr(eval_runner, "reviewer_node", _fail_if_called)

    async with async_session_factory() as db:
        result = await eval_runner.run_pass1(
            db, corpus_path=corpus_path, manifest_path=manifest_path,
            snapshot_dir=tmp_path / "snapshots", daily_cap=1000, safety_margin_pct=0.9,
        )

    # Full return shape, not just sites_crawled: proves Pass 1b was actually
    # reached and stopped correctly, not skipped by an unrelated bug that
    # happens to also leave sites_crawled == 2.
    assert result["sites_crawled"] == 2
    assert result["budget_stopped"] is True
    assert result["violations_reviewed"] == 0

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["sites"]["1"]["crawl_detect_status"] == "done"
    assert manifest["sites"]["2"]["crawl_detect_status"] == "done"


async def test_run_pass1_raises_when_llm_mocked(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    corpus_path = _write_corpus_csv(tmp_path / "corpus.csv", FAKE_CORPUS[:1])
    manifest_path = tmp_path / "manifest.json"

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("crawl_site should not be called when LLM_MOCK is enabled")
    monkeypatch.setattr(crawler, "crawl_site", _fail_if_called)

    async with async_session_factory() as db:
        with pytest.raises(eval_runner.LlmMockEnabledError):
            await eval_runner.run_pass1(
                db, corpus_path=corpus_path, manifest_path=manifest_path,
                snapshot_dir=tmp_path / "snapshots",
            )

    # Strongest assertion here: proves the guard fires before
    # load_or_init_manifest even runs, not just before reviewer_node/crawl_site.
    assert not manifest_path.exists()
