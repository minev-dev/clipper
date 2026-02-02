import datetime
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
