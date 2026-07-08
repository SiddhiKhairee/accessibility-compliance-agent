"""
test_infra_smoke.py — Phase 2.5a infrastructure verification only.

Proves the test-DB + migration + env plumbing works end to end. Not a
regression test for any app behavior — that's 2.5b/2.5c.
"""
import os

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_migrations_created_sites_table(test_engine):
    async with test_engine.connect() as conn:
        result = await conn.execute(text("SELECT to_regclass('public.sites')"))
        assert result.scalar() is not None


def test_llm_mock_forced_in_test_env():
    assert os.environ.get("LLM_MOCK") == "true"
