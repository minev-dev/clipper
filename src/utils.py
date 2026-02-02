import datetime
import logging
import pathlib

PROJECT_ROOT = pathlib.Path(__file__).parent.parent

DIST_DIR = PROJECT_ROOT / "dist"
SECRETS_DIR = PROJECT_ROOT / "secrets"


def parse_datetime(value: str) -> datetime.datetime:
    """Parses a datetime string.

    Args:
        value: The datetime string to parse. Can be "now" or an ISO formatted string.

    Returns:
        A datetime object.
    """
    if value == "now":
        return datetime.datetime.now()
    return datetime.datetime.fromisoformat(value)


def get_logger(name: str) -> logging.Logger:
    """Initializes a logger with a StreamHandler set to INFO level.

    Args:
        name: The name of the logger.

    Returns:
        A configured logging.Logger object.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger
