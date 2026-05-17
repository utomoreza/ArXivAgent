"""FastAPI application factory for ArXivAgent.

Creates the app with an asynccontextmanager lifespan that:
  1. Initialises the DB engine and session factory.
  2. Runs the inception backfill (no-op when rows already exist).
  3. Starts the APScheduler (synchronously — never awaited).
On shutdown the engine is disposed and the scheduler stops immediately.
"""

from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from src.api.deps import configure_session_factory
from src.api.routers.digests import router as digests_router
from src.config import get_settings
from src.db.session import create_engine_and_factory
from src.scheduler.jobs import run_inception_backfill, setup_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage DB engine, session factory, inception backfill, and scheduler lifecycle.

    Yields after startup completes; teardown runs after the yield.

    Args:
        app: The FastAPI application instance (unused but required by the protocol).
    """
    settings = get_settings()
    engine, session_factory = create_engine_and_factory(settings.DATABASE_URL)
    configure_session_factory(session_factory)

    await run_inception_backfill(session_factory)

    scheduler = AsyncIOScheduler()
    setup_scheduler(scheduler, session_factory)
    scheduler.start()  # synchronous — do NOT await

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await engine.dispose()


def create_app() -> FastAPI:
    """Build and return the FastAPI application with all routers registered.

    Returns:
        A fully configured FastAPI instance ready for serving.
    """
    app = FastAPI(
        title="ArXivAgent",
        description="Daily arXiv digest and RAG Q&A service",
        lifespan=lifespan,
    )
    app.include_router(digests_router)
    return app


app = create_app()
