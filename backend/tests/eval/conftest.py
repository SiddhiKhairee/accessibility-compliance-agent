"""
conftest.py — Phase 5 eval-scaffolding test setup only.

Same DATABASE_URL-before-import guard as graph/conftest.py: pydantic-settings
gives real environment variables priority over its `env_file`, so setting
DATABASE_URL here before eval_runner.py's first import (which cascades
through llm_client.py/graph.py -> db.py/config.py) redirects the whole
eval layer's DB writes to the test DB for this subpackage.
"""
import os
import sys
from pathlib import Path

import pytest_asyncio

TESTS_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = TESTS_DIR.parent

# TEST_DATABASE_URL is already in os.environ by this point — the parent
# conftest.py (backend/tests/conftest.py) loads .env.test at module level,
# and pytest always collects an ancestor directory's conftest.py before a
# descendant's.
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

sys.path.insert(0, str(BACKEND_DIR / "app"))

import db as db_module  # noqa: E402 - must import after DATABASE_URL override above


@pytest_asyncio.fixture(autouse=True)
async def _dispose_app_db_engine_between_tests():
    """Same rationale as graph/conftest.py's identical fixture: llm_client's
    DB writes and this suite's own LlmCallLog inserts go through db.py's
    module-level pooled engine, shared across the whole pytest session —
    dispose before/after every test so the next checkout always opens a
    fresh connection under whatever event loop is current."""
    await db_module.engine.dispose()
    yield
    await db_module.engine.dispose()
