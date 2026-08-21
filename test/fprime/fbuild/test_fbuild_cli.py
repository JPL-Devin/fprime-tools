"""
Tests for fbuild CLI command handlers
"""

import argparse
from unittest.mock import MagicMock, patch

from fprime.cli.fbuild import purge
from fprime.build.types import BuildType


def _purge_args(force):
    return argparse.Namespace(command="purge", force=force, build_cache=None)


def _purge_build(tmp_path, exists=True, install_dir=None):
    purge_build = MagicMock()
    build_dir = tmp_path / "build-fprime-automatic-native"
    if exists:
        build_dir.mkdir()
    purge_build.build_dir = build_dir
    purge_build.build_type = BuildType.BUILD_NORMAL
    purge_build.install_dest_exists.return_value = install_dir
    return purge_build


@patch("fprime.cli.fbuild.Build.get_build_list")
def test_purge_force_purges_existing_directory(mock_get_build_list, tmp_path):
    """Tests that purge --force purges an existing build directory without prompting"""
    purge_build = _purge_build(tmp_path)
    mock_get_build_list.return_value = [purge_build]
    purge(MagicMock(), _purge_args(force=True))
    purge_build.purge.assert_called_once()
    _, kwargs = mock_get_build_list.call_args
    assert kwargs.get("ignore_invalid") is True


@patch("fprime.cli.fbuild.Build.get_build_list")
def test_purge_force_skips_missing_directory(mock_get_build_list, tmp_path, capsys):
    """Tests that purge --force skips a missing build directory"""
    purge_build = _purge_build(tmp_path, exists=False)
    mock_get_build_list.return_value = [purge_build]
    purge(MagicMock(), _purge_args(force=True))
    purge_build.purge.assert_not_called()
    assert "Skipping purge" in capsys.readouterr().out


@patch("fprime.cli.fbuild.confirm")
@patch("fprime.cli.fbuild.Build.get_build_list")
def test_purge_confirm_declined(mock_get_build_list, mock_confirm, tmp_path):
    """Tests that declining the confirmation prompt skips the purge"""
    purge_build = _purge_build(tmp_path)
    mock_get_build_list.return_value = [purge_build]
    mock_confirm.return_value = False
    purge(MagicMock(), _purge_args(force=False))
    purge_build.purge.assert_not_called()
    purge_build.purge_install.assert_not_called()


@patch("fprime.cli.fbuild.confirm")
@patch("fprime.cli.fbuild.Build.get_build_list")
def test_purge_confirm_accepted_with_install(
    mock_get_build_list, mock_confirm, tmp_path
):
    """Tests that accepting the prompts purges the build and install directories"""
    purge_build = _purge_build(tmp_path, install_dir=tmp_path / "build-artifacts")
    mock_get_build_list.return_value = [purge_build]
    mock_confirm.return_value = True
    purge(MagicMock(), _purge_args(force=False))
    purge_build.purge.assert_called_once()
    purge_build.purge_install.assert_called_once()
