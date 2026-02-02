import datetime
import pathlib

from src import utils


def test_project_root_exists():
    assert utils.PROJECT_ROOT.exists()
    assert utils.PROJECT_ROOT.is_dir()


def test_dist_dir_path():
    assert isinstance(utils.DIST_DIR, pathlib.Path)
    assert utils.DIST_DIR.name == "dist"
    assert utils.DIST_DIR == utils.PROJECT_ROOT / "dist"


def test_secrets_dir_path():
    assert isinstance(utils.SECRETS_DIR, pathlib.Path)
    assert utils.SECRETS_DIR.name == "secrets"
    assert utils.SECRETS_DIR == utils.PROJECT_ROOT / "secrets"


def test_parse_datetime_now():
    dt_now = utils.parse_datetime("now")
    assert isinstance(dt_now, datetime.datetime)
    # Allow a small delta for execution time
    assert (datetime.datetime.now() - dt_now).total_seconds() < 1


def test_parse_datetime_iso():
    iso_str = "2023-10-27T10:00:00"
    dt_iso = utils.parse_datetime(iso_str)
    assert isinstance(dt_iso, datetime.datetime)
    assert dt_iso == datetime.datetime(2023, 10, 27, 10, 0, 0)
