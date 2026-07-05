"""
db.py — async engine/session plumbing, kept out of main.py so that file can
stay focused on routes + orchestration.
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)

# expire_on_commit=False is required, not cosmetic: without it, accessing
# e.g. scan.id/scan.status right after `await db.commit()` (to build a
# response model) triggers an implicit attribute refresh that needs another
# await, which can raise under AsyncSession if done outside a greenlet
# context.
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_engine() -> None:
    """Startup check: fail fast if Postgres is unreachable, rather than on
    the first request. Deliberately does NOT call Base.metadata.create_all()
    — schema changes go through Alembic only, never auto-created at app
    startup (see CLAUDE.md: "DB schema changes go through a migration,
    never hand-edited in prod")."""
    async with engine.connect():
        pass


async def dispose_engine() -> None:
    await engine.dispose()


async def get_db():
    async with async_session_factory() as session:
        yield session
