"""Tests for fprime.build.targets.check"""

from unittest.mock import patch

import pytest

from fprime.build.targets.check import Check
from fprime.build.targets.target import TargetScope


def test_execute_all_missing_ctest():
    """When ctest is not on the PATH, execute_all raises without running a subprocess"""
    check = Check(scope=TargetScope.LOCAL)
    with (
        patch("fprime.build.targets.check.shutil.which", return_value=None),
        patch("fprime.build.targets.check.subprocess.run") as mock_run,
    ):
        with pytest.raises(FileNotFoundError, match="CTest executable not found"):
            check.execute_all(None, ([], None), ({}, [], {}))
        mock_run.assert_not_called()


def test_resolve_test_directory_with_file(tmp_path):
    """When test-dir.fprime-util exists, its content is used as the test directory"""
    test_dir = tmp_path / "actual_test_dir"
    test_dir.mkdir()

    test_dir_file = tmp_path / Check.TEST_DIR_FILE
    test_dir_file.write_text(str(test_dir))

    result = Check._resolve_test_directory(tmp_path)
    assert result == test_dir


def test_resolve_test_directory_relative_path(tmp_path):
    """When test-dir.fprime-util contains a relative path, it resolves against build cache path"""
    test_dir = tmp_path / "subdir" / "tests"
    test_dir.mkdir(parents=True)

    test_dir_file = tmp_path / Check.TEST_DIR_FILE
    test_dir_file.write_text("subdir/tests")

    result = Check._resolve_test_directory(tmp_path)
    assert result == test_dir.resolve()


def test_resolve_test_directory_no_file(tmp_path):
    """When test-dir.fprime-util does not exist, falls back to build cache path"""
    result = Check._resolve_test_directory(tmp_path)
    assert result == tmp_path


def test_resolve_test_directory_parent_relative(tmp_path):
    """When test-dir.fprime-util contains a parent-relative path (e.g. ../..), it resolves correctly"""
    # Simulate: build_cache_path is tmp_path/deploy, test dir is tmp_path (the parent)
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir()

    test_dir_file = deploy_dir / Check.TEST_DIR_FILE
    test_dir_file.write_text("..")

    result = Check._resolve_test_directory(deploy_dir)
    assert result == tmp_path.resolve()
