"""
Temporary manual test script — proves axe-core can run against a
Playwright-loaded page and produce violation data. Not the real
detector.py module; no crawler integration or DB yet.

Usage: python detector_standalone_test.py <url>
"""
import asyncio
import sys

from axe_playwright_python.async_playwright import Axe
from playwright.async_api import async_playwright


async def main(url: str) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            # networkidle waits for JS-rendered content to settle, since
            # accessibility violations often live there and we need the
            # fully-rendered DOM. Slower than "load"/"domcontentloaded" —
            # Step 4 adds a faster fallback strategy for pages that never
            # go idle.
            await page.goto(url, wait_until="networkidle", timeout=10000)

            results = await Axe().run(page)
            print(f"Violations found: {results.violations_count}")
            print(results.generate_report())
        except Exception as e:
            print(f"Failed to scan {url}: {e}")
        finally:
            await browser.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python detector_standalone_test.py <url>")
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))
