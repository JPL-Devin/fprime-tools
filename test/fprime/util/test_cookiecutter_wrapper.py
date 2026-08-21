"""
Tests for fprime.tools.cookiecutter
"""

from unittest.mock import MagicMock, patch

import pytest
from cookiecutter.main import cookiecutter

from fprime.build.builder import Build
from fprime.tools.cookiecutter import (
    find_nearest_cmake_file,
    new_component,
    new_deployment,
    new_module,
    new_rule_based_testing,
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


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Pytest fixture for a minimal project root with a mocked Build"""
    proj_root = tmp_path / "proj"
    proj_root.mkdir()
    (proj_root / "CMakeLists.txt").write_text("# root\n")
    monkeypatch.chdir(proj_root)
    build = MagicMock(spec=Build)
    build.get_settings.side_effect = lambda key, default=None: (
        proj_root if key == "project_root" else default
    )
    build.cmake_root = proj_root
    return proj_root, build


def _no_input_cookiecutter(*args, **kwargs):
    return cookiecutter(*args, no_input=True, **kwargs)


@patch("fprime.tools.cookiecutter.register_with_cmake")
@patch("fprime.tools.cookiecutter.confirm", return_value=False)
@patch("fprime.tools.cookiecutter.cookiecutter", side_effect=_no_input_cookiecutter)
def test_new_component_instantiates_template(
    mock_cc, mock_confirm, mock_register, project
):
    proj_root, build = project
    args = MagicMock(force=False, overwrite=False)
    assert new_component(build, args) == 0
    assert (proj_root / "MyComponent" / "MyComponent.fpp").is_file()
    mock_register.assert_called_once()


@patch("fprime.tools.cookiecutter.register_with_cmake")
@patch("fprime.tools.cookiecutter.cookiecutter", side_effect=_no_input_cookiecutter)
def test_new_deployment_instantiates_template(mock_cc, mock_register, project):
    proj_root, build = project
    args = MagicMock(force=False, overwrite=False, phased=False)
    assert new_deployment(build, args) == 0
    assert (proj_root / "MyDeployment" / "CMakeLists.txt").is_file()
    mock_register.assert_called_once()


@patch("fprime.tools.cookiecutter.register_with_cmake")
@patch("fprime.tools.cookiecutter.cookiecutter", side_effect=_no_input_cookiecutter)
def test_new_subtopology_instantiates_template(mock_cc, mock_register, project):
    proj_root, build = project
    args = MagicMock(overwrite=False)
    assert new_subtopology(build, args) == 0
    assert (proj_root / "MySubtopology").is_dir()
    mock_register.assert_called_once()


@patch("fprime.tools.cookiecutter.register_with_cmake")
@patch("fprime.tools.cookiecutter.cookiecutter", side_effect=_no_input_cookiecutter)
def test_new_module_instantiates_template(mock_cc, mock_register, project):
    proj_root, build = project
    args = MagicMock(overwrite=False, path=str(proj_root))
    assert new_module(build, args) == 0
    assert (proj_root / "MyModule" / "CMakeLists.txt").is_file()
    mock_register.assert_called_once()


@patch("fprime.tools.cookiecutter.cookiecutter", side_effect=_no_input_cookiecutter)
def test_new_rule_based_testing_instantiates_template(mock_cc, project):
    proj_root, build = project
    args = MagicMock()
    assert new_rule_based_testing(build, args) == 0
    assert (proj_root / "test" / "ut").is_dir()


@patch("fprime.tools.cookiecutter.register_with_cmake")
@patch("fprime.tools.cookiecutter.confirm", return_value=False)
@patch("fprime.tools.cookiecutter.cookiecutter")
def test_new_component_honors_overwrite(mock_cc, mock_confirm, mock_register, project):
    proj_root, build = project
    mock_cc.return_value = str(proj_root / "MyComponent")
    args = MagicMock(force=False, overwrite=True)
    assert new_component(build, args) == 0
    assert mock_cc.call_args.kwargs["overwrite_if_exists"] is True
