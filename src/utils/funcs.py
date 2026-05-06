import logging

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
