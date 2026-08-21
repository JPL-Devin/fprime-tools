"""
Tests for fprime.util.cookiecutter_wrapper
"""

import pytest
from unittest.mock import MagicMock, patch

from cookiecutter.exceptions import OutputDirExistsException, UnknownRepoType

from fprime.util.cookiecutter_wrapper import (
    find_nearest_cmake_file,
    is_valid_name,
    new_component,
    new_module,
    new_subtopology,
)


@pytest.fixture
def file_structure(tmp_path):
    """Pytest fixture for a temporary file structure"""
    proj_root = tmp_path
    component_dir = proj_root / "component"
    component_subdir = component_dir / "sub"
    deployment_dir = proj_root / "deployment"

    component_dir.mkdir()
    component_subdir.mkdir()
    deployment_dir.mkdir()

    (proj_root / "project.cmake").touch()
    (proj_root / "CMakeLists.txt").touch()

    return proj_root, component_dir, component_subdir, deployment_dir


def test_find_nearest_cmake_in_component_parent(file_structure):
    """Test finding CMakeLists.txt in a component's parent directory"""
    proj_root, component_dir, component_subdir, deployment_dir = file_structure
    (component_dir / "CMakeLists.txt").touch()

    found_path = find_nearest_cmake_file(component_subdir, deployment_dir, proj_root)
    assert found_path == (component_dir / "CMakeLists.txt")


def test_find_nearest_cmake_project_cmake(file_structure):
    """Test falling back to project.cmake"""
    proj_root, component_dir, component_subdir, deployment_dir = file_structure

    found_path = find_nearest_cmake_file(component_subdir, deployment_dir, proj_root)
    assert found_path == (proj_root / "project.cmake")


def test_find_nearest_cmake_no_file(file_structure):
    """Test returning None when no file is found"""
    proj_root, component_dir, component_subdir, deployment_dir = file_structure
    (proj_root / "project.cmake").unlink()
    (proj_root / "CMakeLists.txt").unlink()

    found_path = find_nearest_cmake_file(component_subdir, deployment_dir, proj_root)
    assert found_path is None


class _Args:
    """Simple argparse.Namespace stand-in"""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _build_mock(tmp_path):
    build = MagicMock()
    build.get_settings.return_value = None
    build.cmake_root = tmp_path
    return build


@patch("fprime.util.cookiecutter_wrapper.register_with_cmake")
@patch("fprime.util.cookiecutter_wrapper.run_impl", return_value=True)
@patch("fprime.util.cookiecutter_wrapper.check_path_is_within_fprime_module")
@patch("fprime.util.cookiecutter_wrapper.cookiecutter")
def test_new_component_honors_overwrite(
    mock_cookiecutter, mock_check, mock_run_impl, mock_register, tmp_path, monkeypatch
):
    """Tests that new --component passes --overwrite through to cookiecutter"""
    mock_check.return_value = False
    mock_cookiecutter.return_value = str(tmp_path / "MyComponent")
    monkeypatch.chdir(tmp_path)

    assert new_component(_build_mock(tmp_path), _Args(force=False, overwrite=True)) == 0
    assert mock_cookiecutter.call_args.kwargs["overwrite_if_exists"] is True


@patch("fprime.util.cookiecutter_wrapper.cookiecutter")
def test_new_module_reports_unknown_repo(mock_cookiecutter, tmp_path, capsys):
    """Tests that an invalid template source returns an error for new --module"""
    mock_cookiecutter.side_effect = UnknownRepoType()

    result = new_module(
        _build_mock(tmp_path),
        _Args(overwrite=False, path=str(tmp_path)),
        source="not-a-template",
    )
    assert result == 1
    assert "not a valid cookiecutter template" in capsys.readouterr().err


@patch("fprime.util.cookiecutter_wrapper.cookiecutter")
def test_new_subtopology_output_dir_exists(mock_cookiecutter, tmp_path, capsys):
    """Tests the existing-output-directory error path"""
    mock_cookiecutter.side_effect = OutputDirExistsException("'X' already exists")

    result = new_subtopology(_build_mock(tmp_path), _Args(overwrite=False))
    assert result == 1
    assert "Use --overwrite" in capsys.readouterr().err


def test_is_valid_name():
    """Tests name validation and its non-string error"""
    assert is_valid_name("GoodName") == "valid"
    assert is_valid_name("bad name") == " "
    with pytest.raises(ValueError):
        is_valid_name(None)
