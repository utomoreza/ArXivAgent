"""Service entry point for ArXivAgent.

Configures structured JSON logging from settings.LOG_LEVEL, then starts the
FastAPI application with uvicorn.
"""

import logging
import sys

import uvicorn

from src.api.app import app
from src.config import get_settings


def _configure_logging(level: str) -> None:
    """Set up root logger with a structured format and the given level.

    Args:
        level: Logging level string, e.g. "DEBUG", "INFO", "ERROR".
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )


if __name__ == "__main__":
    settings = get_settings()
    _configure_logging(settings.LOG_LEVEL)
    uvicorn.run(app, host="0.0.0.0", port=8000)
