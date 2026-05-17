"""FastAPI application factory for ArXivAgent.

Creates the app with an asynccontextmanager lifespan that:
  1. Initialises the DB engine and session factory.
  2. Starts the APScheduler (synchronously — never awaited).
  3. Fires the inception backfill as a background task so the server starts
     accepting requests immediately — the backfill is a no-op on subsequent runs.
On shutdown the engine is disposed and the scheduler stops immediately.
"""

import asyncio
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from src.api.deps import configure_session_factory
from src.api.routers.digests import router as digests_router
from src.api.routers.qa import router as qa_router
from src.config import get_settings
from src.db.session import create_engine_and_factory
from src.scheduler.jobs import run_inception_backfill, setup_scheduler
from src.utils.funcs import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage DB engine, session factory, inception backfill, and scheduler lifecycle.

    The inception backfill is launched as a background asyncio task so the
    server begins accepting requests immediately. On subsequent startups
    run_inception_backfill exits instantly (idempotent). Yields after
    scheduler starts; teardown runs after the yield.

    Args:
        app: The FastAPI application instance (unused but required by the protocol).
    """
    settings = get_settings()
    engine, session_factory = create_engine_and_factory(settings.DATABASE_URL)
    configure_session_factory(session_factory)

    scheduler = AsyncIOScheduler()
    setup_scheduler(scheduler, session_factory)
    scheduler.start()  # synchronous — do NOT await

    backfill_task = asyncio.create_task(run_inception_backfill(session_factory))
    logger.info("inception backfill started in background")

    try:
        yield
    finally:
        backfill_task.cancel()
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
    app.include_router(qa_router)
    return app


app = create_app()
