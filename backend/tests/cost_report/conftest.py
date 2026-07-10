"""
conftest.py — Phase 4 cost_report.py test setup only.

Same DATABASE_URL-before-import guard as api/conftest.py and
graph/conftest.py: setting DATABASE_URL here before db.py's first import
redirects cost_report.py's module-level engine to the test DB for this
subpackage. Also carries the same stale-pooled-connection dispose fixture
those two subpackages needed (see graph/conftest.py's docstring for the
root cause) — this subpackage's tests build fixture rows via
async_session_factory interleaved across separate event loops too.
"""
import os
import sys
from pathlib import Path

import pytest_asyncio

TESTS_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = TESTS_DIR.parent

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

sys.path.insert(0, str(BACKEND_DIR / "app"))

import db as db_module  # noqa: E402 - must import after DATABASE_URL override above


@pytest_asyncio.fixture(autouse=True)
async def _dispose_app_db_engine_between_tests():
    await db_module.engine.dispose()
    yield
    await db_module.engine.dispose()
