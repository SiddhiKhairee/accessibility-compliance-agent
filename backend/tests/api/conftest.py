"""
conftest.py — Phase 2.5b API round-trip test setup only.

Points main.py's DB layer at the test DB *without* touching
config.py/db.py/main.py: pydantic-settings gives real environment
variables priority over its `env_file`, so setting DATABASE_URL here
before main.py's first import (which pulls in config.py -> db.py, both of
which read settings.DATABASE_URL once at import time) redirects the whole
app to the test DB for this subpackage only. backend/tests/graph/conftest.py
(added in Phase 2.5c) does the identical override for its own subpackage —
safe regardless of which one's import runs first in a full-suite run,
since both set DATABASE_URL to the same TEST_DATABASE_URL value.
"""
import os
import sys
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

TESTS_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = TESTS_DIR.parent

# TEST_DATABASE_URL is already in os.environ by this point — the parent
# conftest.py (backend/tests/conftest.py) loads .env.test at module level,
# and pytest always collects an ancestor directory's conftest.py before a
# descendant's.
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

sys.path.insert(0, str(BACKEND_DIR / "app"))

import db as db_module  # noqa: E402 - must import after DATABASE_URL override above
import main  # noqa: E402 - must import after DATABASE_URL override above


@pytest_asyncio.fixture
async def api_client(run_migrations):
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture(autouse=True)
async def _dispose_app_db_engine_between_tests():
    """Same fix graph/conftest.py already applies, for the same reason —
    see that file's docstring. Needed here too as of Phase 4:
    test_dashboard_endpoints.py added direct async_session_factory usage
    (building fixture rows) interleaved with test_scan_roundtrip.py's
    Playwright-heavy crawl across separate function-scoped event loops in
    this same directory, reproducing the identical stale-pooled-connection
    AttributeError."""
    await db_module.engine.dispose()
    yield
    await db_module.engine.dispose()
