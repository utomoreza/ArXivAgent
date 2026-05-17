"""Integration tests for the FastAPI app factory (T029).

Verifies that the lifespan correctly initialises the DB engine, session
factory, inception backfill, and APScheduler, and tears everything down
cleanly on shutdown.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_create_app_returns_fastapi_instance():
    """create_app must return a FastAPI application with the digests router mounted."""
    from src.api.app import create_app

    application = create_app()
    assert isinstance(application, FastAPI)
    routes = {r.path for r in application.routes}
    assert "/digests/daily/{date}" in routes
    assert "/digests/weekly/{week_start_date}" in routes


@pytest.mark.asyncio
async def test_lifespan_startup_and_shutdown():
    """Lifespan must initialise engine/factory, run backfill, start scheduler, then tear down."""
    mock_engine = AsyncMock()
    mock_factory = MagicMock()
    mock_scheduler = MagicMock()

    with (
        patch("src.api.app.create_engine_and_factory", return_value=(mock_engine, mock_factory)) as mock_create,
        patch("src.api.app.configure_session_factory") as mock_configure,
        patch("src.api.app.run_inception_backfill", new_callable=AsyncMock) as mock_backfill,
        patch("src.api.app.AsyncIOScheduler", return_value=mock_scheduler),
        patch("src.api.app.setup_scheduler") as mock_setup,
        patch("src.api.app.get_settings") as mock_settings,
    ):
        mock_settings.return_value.DATABASE_URL = "postgresql+asyncpg://u:p@h/db"

        from src.api.app import create_app

        application = create_app()

        # Trigger the lifespan directly via the router's context manager.
        async with application.router.lifespan_context(application):
            # Assertions during the running window (startup complete)
            mock_create.assert_called_once_with("postgresql+asyncpg://u:p@h/db")
            mock_configure.assert_called_once_with(mock_factory)
            mock_backfill.assert_awaited_once_with(mock_factory)
            mock_setup.assert_called_once_with(mock_scheduler, mock_factory)
            mock_scheduler.start.assert_called_once()

        # Assertions after shutdown
        mock_scheduler.shutdown.assert_called_once_with(wait=False)
        mock_engine.dispose.assert_awaited_once()
