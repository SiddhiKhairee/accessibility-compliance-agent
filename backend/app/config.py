"""
config.py — environment-driven settings for the API layer.

Resolves `.env` via an absolute path (Path(__file__).parent), not the bare
string ".env", so it works regardless of the cwd the process is launched
from. This matters because crawler.py/detector.py use flat same-directory
imports (`from detector import ...`), which means the whole app is already
run with cwd = backend/app/ by convention (see main.py's module docstring) —
but settings resolution shouldn't silently depend on that convention holding.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_PATH = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_PATH, env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str
    ENVIRONMENT: str = "development"
    GROQ_API_KEY: str = ""
    # Phase 4: the one local dev origin the dashboard's CORS policy allows.
    # Never a wildcard — this project has no auth/multi-tenancy layer, so an
    # open CORS policy would have nothing else guarding it.
    FRONTEND_ORIGIN: str = "http://localhost:5173"
    # Phase 5: eval_runner.py's daily-RPD budget guard. This is a fallback
    # default, not a verified account limit — confirm the real number at
    # console.groq.com/settings/limits before relying on it for a real
    # Pass 1 run. Separate from llm_client.py's existing per-minute
    # per-model token pacing (design.md Section 8b) — that reacts to Groq's
    # own response headers; this tracks a daily total via llm_call_logs.
    EVAL_DAILY_CALL_CAP: int = 1000
    EVAL_DAILY_CAP_SAFETY_MARGIN_PCT: float = 0.9
    # Phase 5 follow-up (design.md Section 14h, 2026-07-19): a per-account,
    # per-model *daily token* cap confirmed live via a real 429 body
    # ("Rate limit reached ... on tokens per day (TPD): Limit 200000") for
    # qwen/qwen3.6-27b — distinct from EVAL_DAILY_CALL_CAP (request count)
    # and from llm_client.py's existing per-minute token pacing
    # (TOKEN_SAFETY_MARGIN). Unlike EVAL_DAILY_CALL_CAP's default, 200,000
    # is the literal confirmed limit as of that date, not a guess — still
    # reconfirm at console.groq.com/settings/limits if MODEL_NAME changes
    # again. Reuses EVAL_DAILY_CAP_SAFETY_MARGIN_PCT rather than a second
    # margin setting: the margin's purpose (headroom for concurrent
    # account usage) applies the same regardless of which unit is measured.
    EVAL_DAILY_TOKEN_CAP: int = 200_000


settings = Settings()
