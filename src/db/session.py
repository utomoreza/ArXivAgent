"""SQLAlchemy async engine and session factory for ArXivAgent.

The engine and session_factory are initialised by the FastAPI lifespan in
app.py; this module exposes the get_session dependency so routers and
background jobs can obtain a session without importing app internals.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine_and_factory(
    database_url: str,
    echo: bool = False,
) -> tuple:
    """Create an async engine and session factory from a database URL.

    Args:
        database_url: SQLAlchemy async URL, e.g. postgresql+asyncpg://...
        echo: If True, log all SQL statements (useful for debugging).

    Returns:
        (engine, session_factory) tuple. Caller owns both objects and must
        call engine.dispose() on shutdown.
    """
    engine = create_async_engine(database_url, echo=echo)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


async def get_session(
    session_factory: async_sessionmaker,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a single AsyncSession for use as a FastAPI dependency.

    Args:
        session_factory: The async_sessionmaker created during app lifespan.

    Yields:
        An AsyncSession scoped to one request. The session is closed (but not
        committed) when the generator exits; callers must commit explicitly.
    """
    async with session_factory() as session:
        yield session
