"""
crawler.py — same-domain, breadth-limited site crawler.

Given a starting URL, discovers up to `max_pages` pages on the same domain
(BFS, capped at `max_depth`), prioritizing links that match critical-path
URL patterns (checkout, login, search, etc. — see design.md Section 4),
loads each page with Playwright, and saves a raw HTML snapshot per page.

Defensive per CLAUDE.md: each page load has its own timeout; pages that
fail to load are skipped and logged rather than crashing the whole crawl.
Authenticated pages are out of v1 scope — this crawler never logs in, so
anything requiring a session naturally fails to load (redirect/etc.) and
gets skipped like any other failed page.

Bot-blocking (Phase 4.6): Playwright's `page.goto()` only raises on
network-level failures (DNS, connection refused, timeout) — it does not
raise on 4xx/5xx HTTP responses. A blocked/rate-limited site (403/429/503)
or a 200 CAPTCHA/Cloudflare-challenge page would otherwise be silently
recorded as a normal "loaded" page and scanned for violations. Both are
explicitly detected below and routed into the same failed/skip path.
"""
import asyncio
import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Page, async_playwright

from detector import Violation, detect_violations

DEFAULT_MAX_PAGES = 15
DEFAULT_MAX_DEPTH = 2
PAGE_LOAD_TIMEOUT_MS = 10000
DETECTION_TIMEOUT_S = 10

# Critical-path URL patterns (design.md Section 4 / PLAN.md Phase 0) —
# links matching these are crawled before generic links, so a capped crawl
# still reliably reaches the pages that matter most for WCAG impact.
PRIORITY_PATTERNS = [
    "checkout", "cart", "login", "signin", "signup", "register",
    "contact", "search",
]

# HTTP statuses that indicate bot-blocking/rate-limiting rather than a real
# page (404/500/etc. are left alone — those are real app errors, not
# blocking, and should still be recorded as "loaded").
BLOCKED_STATUS_CODES = {403, 429, 503}

# Best-effort substrings (lowercase) seen in common CAPTCHA/anti-bot
# interstitial pages that return HTTP 200. Not exhaustive — a heuristic
# sniff, not a robust anti-bot-page classifier.
CHALLENGE_MARKERS = (
    "just a moment",
    "checking your browser before accessing",
    "enable javascript and cookies to continue",
    "verify you are human",
    "attention required! | cloudflare",
    "sorry, you have been blocked",
)

# Matches the /data/raw_html/ convention already reserved in .gitignore
# for schema.md's `raw_html_snapshot_path` field.
SNAPSHOT_DIR = Path(__file__).parent.parent.parent / "data" / "raw_html"


@dataclass
class CrawledPage:
    url: str
    depth: int
    status: str  # "loaded" or "failed"
    title: str | None = None
    snapshot_path: str | None = None
    failure_reason: str | None = None
    violations: list[Violation] = field(default_factory=list)
    detection_error: str | None = None


def _same_domain(url: str, root_domain: str) -> bool:
    return urlparse(url).netloc == root_domain


def _priority_score(url: str) -> int:
    path = urlparse(url).path.lower()
    return 0 if any(p in path for p in PRIORITY_PATTERNS) else 1


def _snapshot_filename(url: str) -> str:
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    return f"{digest}.html"


async def _extract_same_domain_links(page: Page, root_domain: str) -> list[str]:
    hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    links = set()
    for href in hrefs:
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        if _same_domain(href, root_domain):
            links.add(href.split("#")[0])
    return list(links)


async def crawl_site(
    start_url: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    snapshot_dir: Path = SNAPSHOT_DIR,
) -> list[CrawledPage]:
    """Crawl up to `max_pages` same-domain pages, prioritizing critical-path URLs.

    `max_pages` bounds total page *attempts* (loaded + failed), not just
    successful loads — this keeps crawl runtime bounded even against a site
    that fails to load most of its pages.
    """
    root_domain = urlparse(start_url).netloc
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    visited: set[str] = set()
    results: list[CrawledPage] = []
    queue: list[tuple[str, int]] = [(start_url, 0)]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        while queue and len(results) < max_pages:
            # Re-sort remaining queue each pass so priority pages discovered
            # at any depth jump ahead of already-queued generic pages.
            queue.sort(key=lambda item: (_priority_score(item[0]), item[1]))
            url, depth = queue.pop(0)

            if url in visited:
                continue
            visited.add(url)

            page = await browser.new_page()
            try:
                # networkidle waits for JS-rendered content to settle, since
                # accessibility violations often live there and we need the
                # fully-rendered DOM. Slower than "load"/"domcontentloaded" —
                # Step 4 adds a faster fallback strategy for pages that never
                # go idle.
                response = await page.goto(url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT_MS)

                if response is not None and response.status in BLOCKED_STATUS_CODES:
                    results.append(CrawledPage(
                        url=url, depth=depth, status="failed",
                        failure_reason=f"blocked (status {response.status})",
                    ))
                    continue

                title = await page.title()
                html = await page.content()

                if any(marker in html.lower() for marker in CHALLENGE_MARKERS):
                    results.append(CrawledPage(
                        url=url, depth=depth, status="failed",
                        failure_reason="blocked (challenge page detected)",
                    ))
                    continue

                snapshot_path = snapshot_dir / _snapshot_filename(url)
                snapshot_path.write_text(html, encoding="utf-8")

                # Detection runs on its own timeout and its own try/except,
                # separate from the page-load try/except above: a page that
                # loaded fine but hangs/errors during axe-core analysis is a
                # detection failure, not a load failure, and shouldn't be
                # misclassified as "failed" when the page itself is fine.
                violations: list[Violation] = []
                detection_error: str | None = None
                try:
                    violations = await asyncio.wait_for(
                        detect_violations(page), timeout=DETECTION_TIMEOUT_S
                    )
                except Exception as e:
                    detection_error = str(e)

                results.append(CrawledPage(
                    url=url, depth=depth, status="loaded",
                    title=title, snapshot_path=str(snapshot_path),
                    violations=violations, detection_error=detection_error,
                ))

                if depth < max_depth:
                    for link in await _extract_same_domain_links(page, root_domain):
                        if link not in visited:
                            queue.append((link, depth + 1))

            except Exception as e:
                results.append(CrawledPage(
                    url=url, depth=depth, status="failed",
                    failure_reason=str(e),
                ))
            finally:
                await page.close()

        await browser.close()

    return results


async def _main(start_url: str) -> None:
    pages = await crawl_site(start_url)
    for pg in pages:
        line = f"[{pg.status}] depth={pg.depth} {pg.url}"
        if pg.status == "failed":
            line += f" — {pg.failure_reason}"
        elif pg.detection_error:
            line += f" — detection_error: {pg.detection_error}"
        else:
            line += f" — {len(pg.violations)} violations"
        print(line)

    loaded = sum(1 for pg in pages if pg.status == "loaded")
    total_violations = sum(len(pg.violations) for pg in pages)
    print(f"\n{loaded}/{len(pages)} pages loaded successfully.")
    print(f"Total violations found: {total_violations}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python crawler.py <url>")
        sys.exit(1)

    asyncio.run(_main(sys.argv[1]))
