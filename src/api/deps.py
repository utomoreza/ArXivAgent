"""FastAPI dependency for injecting an async DB session.

The session factory is configured by the app lifespan (T029). Tests override
``get_session`` via ``app.dependency_overrides``.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_session_factory: async_sessionmaker | None = None


def configure_session_factory(factory: async_sessionmaker) -> None:
    """Store the session factory created during app lifespan startup."""
    global _session_factory
    _session_factory = factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession from the configured factory.

    Raises:
        RuntimeError: If called before ``configure_session_factory``.
    """
    if _session_factory is None:
        raise RuntimeError("Session factory not configured — call configure_session_factory first.")
    async with _session_factory() as session:
        yield session
