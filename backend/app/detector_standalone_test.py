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

# Locked v1 WCAG rule set (PLAN.md Phase 0) — the 9 rules fully automatable
# via axe-core, no manual-judgment rules. Everything else axe-core detects
# is out of scope for v1 and must not reach the violations table.
LOCKED_RULE_IDS = [
    "image-alt", "input-image-alt",       # 1. Non-text Content (1.1.1)
    "color-contrast",                      # 2. Contrast Minimum (1.4.3)
    "label", "button-name", "aria-input-field-name",  # 3. Name/Role/Value (4.1.2)
    "tabindex",                            # 4. Keyboard (2.1.1)
    "html-has-lang", "html-lang-valid",    # 5. Language of Page (3.1.1)
    "bypass", "skip-link",                 # 6. Bypass Blocks (2.4.1)
    "duplicate-id-aria",                   # 7. Duplicate ARIA/label IDs (4.1.2)
    "list", "listitem", "definition-list", # 8. Info and Relationships (1.3.1)
    "link-name",                           # 9. Link Purpose (2.4.4)
]


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

            results = await Axe().run(
                page,
                options={"resultTypes": ["violations"], "runOnly": {"type": "rule", "values": LOCKED_RULE_IDS}},
            )
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
