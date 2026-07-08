"""
conftest.py — Phase 2.5c Phase-2-reasoning-layer test setup only.

Same DATABASE_URL-before-import guard as api/conftest.py: pydantic-settings
gives real environment variables priority over its `env_file`, so setting
DATABASE_URL here before graph.py's first import (which cascades through
llm_client.py -> db.py/config.py) redirects the whole reasoning layer's DB
writes to the test DB for this subpackage. Both api/conftest.py and this
file set DATABASE_URL to the same TEST_DATABASE_URL value, so it's safe
regardless of which one's import runs first in a full-suite run.
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
    """llm_client.py's DB writes (_write_log, the Reviewer cache) go through
    db.py's module-level pooled engine (pool_pre_ping=True), a singleton
    created once at import time and shared with any other test subpackage
    that also imports main/db (e.g. api/), all the way across the whole
    pytest session. pytest-asyncio's default function-scoped event loop
    means each test gets a fresh loop, but a pooled asyncpg connection is
    bound to the loop that opened it; reusing one across a different
    test's loop hits the same stale-connection AttributeError 2.5b hit and
    fixed (for test_engine) by switching to NullPool. Can't change db.py's
    poolclass without touching production code, so instead dispose the
    pool both before (in case api/'s tests already ran in this session and
    left a connection bound to their own now-closed loop) and after every
    test here — the next checkout always opens a fresh connection under
    whatever loop is current. Test-only overhead, not a hot path."""
    await db_module.engine.dispose()
    yield
    await db_module.engine.dispose()
