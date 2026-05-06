import asyncio
import functools
import logging
from typing import Any

from src.config import get_settings


# ANSI Color Codes
class Colors:
    GREEN = "\033[32m"
    GREY = "\x1b[38;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    CYAN = "\x1b[36;20m"
    RESET = "\x1b[0m"
    MAGENTA = "\x1b[95m"


class CustomFormatter(logging.Formatter):
    """Assigns different colors to log levels."""

    # You can customize these colors as you like
    LEVEL_COLORS = {
        logging.DEBUG: Colors.CYAN,
        logging.INFO: Colors.GREEN,
        logging.WARNING: Colors.YELLOW,
        logging.ERROR: Colors.MAGENTA,
        logging.CRITICAL: Colors.RED,
    }

    def format(self, record):
        log_fmt = self.LEVEL_COLORS.get(record.levelno, Colors.RESET)
        # We wrap only the levelname and funcName in color, or the whole line
        # Here, we color the entire prefix:
        format_str = f"{log_fmt}[%(levelname)s] %(funcName)s{Colors.RESET}: %(message)s"

        formatter = logging.Formatter(format_str)
        return formatter.format(record)


def _setup_custom_logger():
    """Internal helper to initialize the root logger"""
    handler = logging.StreamHandler()
    handler.setFormatter(CustomFormatter())

    logger = logging.getLogger("ArXivAgent_Logger")
    logger.setLevel(logging.getLevelNamesMapping()[get_settings().LOG_LEVEL])

    if not logger.handlers:
        logger.addHandler(handler)
        logger.propagate = False

    return logger


logger = _setup_custom_logger()


def with_retry(
    max_retries: int = 3,
    base_seconds: float = 1.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Any:
    """Async exponential-backoff retry decorator.

    Retries the wrapped coroutine up to *max_retries* times when one of the
    listed *exceptions* is raised, sleeping ``base_seconds * 2^attempt``
    between each pair of attempts.  Emits a WARNING on every retry and an
    ERROR with full traceback once all attempts are exhausted before re-raising
    the last exception.

    Args:
        max_retries: Total number of attempts (including the first).
        base_seconds: Multiplier for the exponential sleep; sleep on attempt
            ``n`` (0-indexed) is ``base_seconds * 2**n``.
        exceptions: Exception types to catch and retry on.

    Returns:
        Decorator that wraps an async function with retry logic.

    Raises:
        Last caught exception after all attempts are exhausted.
    """
    def decorator(func):  # type: ignore[no-untyped-def]
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    logger.warning(
                        "retry func=%s attempt=%d/%d error=%s",
                        func.__name__,
                        attempt + 1,
                        max_retries,
                        exc,
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(base_seconds * (2**attempt))
            logger.error(
                "exhausted retries func=%s attempts=%d",
                func.__name__,
                max_retries,
                exc_info=last_exc,
            )
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
