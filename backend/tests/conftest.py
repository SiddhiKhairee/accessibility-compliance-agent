"""
conftest.py — Phase 2.5a test infrastructure only.

Runs the real Alembic migration chain against a fully separate test Postgres
(see docker-compose.yml's `postgres_test` service, profile "test") and hands
out a throwaway async engine for tests. Never touches app.db's dev engine or
app.config.Settings (which stays pinned to backend/app/.env, i.e. dev) —
TEST_DATABASE_URL/LLM_MOCK are read straight from the environment after
loading backend/app/.env.test, on purpose, to keep the test DB fully
decoupled from anything dev-configured.
"""
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Matches the flat-import convention backend/app/*.py already uses
# (e.g. `from db import ...`), so future test files can import app modules
# the same way the app itself does.
sys.path.insert(0, str(BACKEND_DIR / "app"))

load_dotenv(BACKEND_DIR / "app" / ".env.test", override=True)

TEST_DATABASE_URL = os.environ["TEST_DATABASE_URL"]


@pytest.fixture(scope="session", autouse=True)
def run_migrations() -> None:
    """Runs the real Alembic chain against the test DB once per session, not
    per test. Must be a sync fixture: Alembic's async env.py template calls
    asyncio.run() internally, which raises if invoked from inside a running
    event loop."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(cfg, "head")


@pytest_asyncio.fixture(scope="session")
async def test_engine(run_migrations: None):
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield engine
    await engine.dispose()
