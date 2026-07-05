"""
Temporary manual test script — proves Playwright can load a real page and
read its title. Not the real crawler.py module; no detection or DB yet.

Usage: python crawler_standalone_test.py <url>
"""
import asyncio
import sys

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
            print(f"Page title: {await page.title()}")
            print(f"Successfully loaded: {url}")
        except Exception as e:
            print(f"Failed to load {url}: {e}")
        finally:
            await browser.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python crawler_standalone_test.py <url>")
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))
