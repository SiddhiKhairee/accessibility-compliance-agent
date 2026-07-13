"""
test_crawler.py — Phase 2.5b regression coverage for crawler.py.

Runs entirely against the local test server (fixtures/server.py) and a
closed local port — never the real internet. `snapshot_dir=tmp_path` on
every call keeps tests from ever writing into the real /data/raw_html/.
"""
import crawler

from fixtures.server import find_unused_port


def _url(test_server, path: str) -> str:
    return f"{test_server.base_url}{path}"


async def test_same_domain_restriction(test_server, tmp_path):
    results = await crawler.crawl_site(
        _url(test_server, "/crawler_site/index.html"),
        max_pages=20, max_depth=2, snapshot_dir=tmp_path,
    )
    urls = [pg.url for pg in results]
    assert not any("external-domain.test" in u for u in urls)
    assert any("index.html" in u for u in urls)


async def test_max_depth_one_excludes_depth_two_and_beyond(test_server, tmp_path):
    results = await crawler.crawl_site(
        _url(test_server, "/crawler_site/index.html"),
        max_pages=20, max_depth=1, snapshot_dir=tmp_path,
    )
    urls = [pg.url for pg in results]
    assert any("page_a.html" in u for u in urls)
    assert not any("page_b.html" in u for u in urls)
    assert not any("page_c.html" in u for u in urls)


async def test_max_depth_two_reaches_depth_two_not_three(test_server, tmp_path):
    results = await crawler.crawl_site(
        _url(test_server, "/crawler_site/index.html"),
        max_pages=20, max_depth=2, snapshot_dir=tmp_path,
    )
    urls = [pg.url for pg in results]
    assert any("page_b.html" in u for u in urls)
    assert not any("page_c.html" in u for u in urls)


async def test_max_pages_caps_total_attempts(test_server, tmp_path):
    results = await crawler.crawl_site(
        _url(test_server, "/crawler_site/index.html"),
        max_pages=2, max_depth=2, snapshot_dir=tmp_path,
    )
    assert len(results) <= 2


async def test_priority_pattern_wins_queue_ordering(test_server, tmp_path):
    """With only 3 slots (index + 2 more), the login page (a priority
    pattern) must beat at least one of the generic depth-1 pages into the
    result set, proving _priority_score actually re-sorts the queue rather
    than leaving it in plain BFS discovery order."""
    results = await crawler.crawl_site(
        _url(test_server, "/crawler_site/index.html"),
        max_pages=3, max_depth=2, snapshot_dir=tmp_path,
    )
    urls = [pg.url for pg in results]
    assert any("priority_login.html" in u for u in urls)
    generic_present = sum(1 for u in urls if "page_d.html" in u or "page_e.html" in u)
    assert generic_present < 2, "expected priority ordering to exclude at least one generic page"


async def test_skip_and_log_on_navigation_timeout(test_server, tmp_path, monkeypatch):
    monkeypatch.setattr(crawler, "PAGE_LOAD_TIMEOUT_MS", 1000)
    results = await crawler.crawl_site(
        _url(test_server, "/slow"),
        max_pages=1, max_depth=0, snapshot_dir=tmp_path,
    )
    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].failure_reason is not None


async def test_skip_and_log_on_connection_refused(tmp_path):
    dead_port = find_unused_port()
    results = await crawler.crawl_site(
        f"http://127.0.0.1:{dead_port}/",
        max_pages=1, max_depth=0, snapshot_dir=tmp_path,
    )
    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].failure_reason is not None


async def test_skip_and_log_on_403_status(test_server, tmp_path):
    results = await crawler.crawl_site(
        _url(test_server, "/blocked_403"),
        max_pages=1, max_depth=0, snapshot_dir=tmp_path,
    )
    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].failure_reason == "blocked (status 403)"


async def test_skip_and_log_on_429_status(test_server, tmp_path):
    results = await crawler.crawl_site(
        _url(test_server, "/blocked_429"),
        max_pages=1, max_depth=0, snapshot_dir=tmp_path,
    )
    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].failure_reason == "blocked (status 429)"


async def test_skip_and_log_on_503_status(test_server, tmp_path):
    results = await crawler.crawl_site(
        _url(test_server, "/blocked_503"),
        max_pages=1, max_depth=0, snapshot_dir=tmp_path,
    )
    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].failure_reason == "blocked (status 503)"


async def test_skip_and_log_on_challenge_page(test_server, tmp_path):
    results = await crawler.crawl_site(
        _url(test_server, "/challenge_page"),
        max_pages=1, max_depth=0, snapshot_dir=tmp_path,
    )
    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].failure_reason == "blocked (challenge page detected)"


async def test_blocked_page_does_not_extract_links(test_server, tmp_path):
    """The challenge page fixture links to page_a.html — the crawler must
    not chase links found on a page it just classified as blocked."""
    results = await crawler.crawl_site(
        _url(test_server, "/challenge_page"),
        max_pages=5, max_depth=1, snapshot_dir=tmp_path,
    )
    urls = [pg.url for pg in results]
    assert len(results) == 1
    assert not any("page_a.html" in u for u in urls)


async def test_timeout_does_not_abort_rest_of_crawl(test_server, tmp_path, monkeypatch):
    """A single failed page (timeout, via /slow) must not crash the whole
    crawl — page_d, discovered from the same start page, should still get
    attempted and succeed."""
    monkeypatch.setattr(crawler, "PAGE_LOAD_TIMEOUT_MS", 1000)
    results = await crawler.crawl_site(
        _url(test_server, "/crawler_site/index_with_slow.html"),
        max_pages=20, max_depth=1, snapshot_dir=tmp_path,
    )
    by_status = {pg.status for pg in results}
    assert "loaded" in by_status
    assert "failed" in by_status
    assert any("page_d.html" in pg.url and pg.status == "loaded" for pg in results)
    assert any("/slow" in pg.url and pg.status == "failed" for pg in results)
