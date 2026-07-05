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


settings = Settings()
