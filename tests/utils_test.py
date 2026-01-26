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
