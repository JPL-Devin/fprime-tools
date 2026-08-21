"""
Mocked-subprocess tests for fbuild plumbing: the execute_known_target auto-refresh
retry, Gcovr argv assembly, and purge force/confirm/missing-dir logic.
"""

from unittest.mock import MagicMock, patch

import pytest

from fprime.fbuild.cli import purge
from fprime.fbuild.cmake import CMakeExecutionException, CMakeHandler
from fprime.fbuild.gcovr import Gcovr
from fprime.fbuild.target import TargetScope
from fprime.fbuild.types import BuildType


@patch("fprime.fbuild.cmake.CMakeHandler.cmake_refresh_cache")
@patch("fprime.fbuild.cmake.CMakeHandler.validate_cmake_cache")
@patch("fprime.fbuild.cmake.CMakeHandler._run_cmake")
def test_auto_refresh_retry_on_no_rule(mock_run, mock_validate, mock_refresh):
    """'No rule to make target' triggers a cache refresh and a retry that can succeed"""
    handler = CMakeHandler()
    mock_run.reset_mock()
    mock_run.side_effect = [
        CMakeExecutionException(
            "failed", ["make: *** No rule to make target 'noop'.  Stop."], True
        ),
        ("stdout", "stderr"),
    ]
    result = handler.execute_known_target(
        "noop", "/fake/build/dir", None, top_target=True, print_output=False
    )
    assert result == ("stdout", "stderr")
    mock_refresh.assert_called_once()
    assert mock_run.call_count == 2


@patch("fprime.fbuild.cmake.CMakeHandler.cmake_refresh_cache")
@patch("fprime.fbuild.cmake.CMakeHandler.validate_cmake_cache")
@patch("fprime.fbuild.cmake.CMakeHandler._run_cmake")
def test_no_auto_refresh_on_other_errors(mock_run, mock_validate, mock_refresh):
    """Any other build error is raised without attempting a cache refresh"""
    handler = CMakeHandler()
    mock_run.reset_mock()
    mock_run.side_effect = CMakeExecutionException(
        "failed", ["error: something else went wrong"], True
    )
    with pytest.raises(CMakeExecutionException):
        handler.execute_known_target(
            "noop", "/fake/build/dir", None, top_target=True, print_output=False
        )
    mock_refresh.assert_not_called()
    assert mock_run.call_count == 1


def make_gcovr_builder(tmp_path):
    """Build a mocked builder suitable for Gcovr.execute"""
    project_root = tmp_path / "proj"
    build_dir = project_root / "build-fprime-automatic-native"
    build_dir.mkdir(parents=True)
    framework = tmp_path / "framework"
    framework.mkdir()
    builder = MagicMock()
    builder.build_dir = build_dir
    builder.settings = {}
    builder.is_project_root.return_value = True
    builder.cmake.verbose = False
    settings = {"project_root": project_root, "framework_path": framework}
    builder.get_settings.side_effect = lambda key, default=None: settings.get(
        key, default
    )
    return builder, project_root, build_dir, framework


DEFAULT_OPTIONS = {
    "--all-sources": False,
    "--comp-ac": False,
    "--port-ac": False,
    "--type-ac": False,
    "--test-ac": False,
    "--sm-ac": False,
    "--test-sources": False,
}


@patch("fprime.fbuild.gcovr.subprocess.call", return_value=0)
@patch("fprime.fbuild.gcovr.shutil.which", return_value="/usr/bin/gcovr")
def test_gcovr_argv_defaults(mock_which, mock_call, tmp_path):
    """Default Gcovr argv excludes autocode/test sources and FW_ASSERT branches"""
    builder, project_root, build_dir, framework = make_gcovr_builder(tmp_path)
    context = project_root
    gcovr = Gcovr(TargetScope.LOCAL)
    gcovr.execute(builder, context, ({}, [], dict(DEFAULT_OPTIONS)))
    argv = mock_call.call_args.args[0]
    assert argv[:4] == [
        "gcovr",
        "-r",
        str(project_root.resolve()),
        str(build_dir.resolve()),
    ]
    joined = " ".join(argv)
    assert "-j" not in argv
    assert ".*ComponentAc.[ch]pp" in joined
    assert ".*/test/.*" in joined
    assert "--exclude-throw-branches" in argv
    assert "--exclude-branches-by-pattern" in argv
    assert f"{framework.resolve()}/Autocoders" in argv
    assert "--print-summary" in argv
    assert f"{context.resolve() / 'coverage'}/summary.txt" in argv
    assert (context.resolve() / "coverage").is_dir()


@patch("fprime.fbuild.gcovr.subprocess.call", return_value=0)
@patch("fprime.fbuild.gcovr.shutil.which", return_value="/usr/bin/gcovr")
def test_gcovr_argv_all_sources_jobs_and_pass_through(mock_which, mock_call, tmp_path):
    """--all-sources removes source exclusions; jobs and pass-through args are forwarded"""
    builder, project_root, build_dir, framework = make_gcovr_builder(tmp_path)
    options = dict(DEFAULT_OPTIONS)
    options["--all-sources"] = True
    gcovr = Gcovr(TargetScope.LOCAL)
    gcovr.execute(builder, project_root, ({"--jobs": 4}, ["--extra-flag"], options))
    argv = mock_call.call_args.args[0]
    joined = " ".join(argv)
    assert ["-j", "4"] == argv[4:6]
    assert "ComponentAc" not in joined
    assert ".*/test/.*" not in joined
    assert argv[-1] == "--extra-flag"


def make_purge_parsed(force):
    """Parsed namespace for the purge command"""
    parsed = MagicMock()
    parsed.command = "purge"
    parsed.force = force
    parsed.build_cache = None
    return parsed


@patch("fprime.fbuild.cli.Build")
def test_purge_force_purges_existing_dir(mock_build_cls, tmp_path):
    """purge --force removes an existing build cache and install dir without confirmation"""
    purge_build = MagicMock()
    purge_build.build_dir = tmp_path
    purge_build.build_type = BuildType.BUILD_NORMAL
    purge_build.install_dest_exists.return_value = tmp_path / "install"
    mock_build_cls.get_build_list.return_value = [purge_build]
    purge(MagicMock(), make_purge_parsed(force=True))
    purge_build.purge.assert_called_once()
    purge_build.purge_install.assert_called_once()


@patch("fprime.fbuild.cli.Build")
def test_purge_force_skips_missing_dir(mock_build_cls, tmp_path):
    """purge --force skips purging when the build cache directory does not exist"""
    purge_build = MagicMock()
    purge_build.build_dir = tmp_path / "does-not-exist"
    purge_build.build_type = BuildType.BUILD_NORMAL
    purge_build.install_dest_exists.return_value = None
    mock_build_cls.get_build_list.return_value = [purge_build]
    purge(MagicMock(), make_purge_parsed(force=True))
    purge_build.purge.assert_not_called()
    purge_build.purge_install.assert_not_called()


@patch("fprime.fbuild.cli.confirm", return_value=False)
@patch("fprime.fbuild.cli.Build")
def test_purge_confirm_declined(mock_build_cls, mock_confirm, tmp_path):
    """purge without --force asks for confirmation and skips on decline"""
    purge_build = MagicMock()
    purge_build.build_dir = tmp_path
    purge_build.build_type = BuildType.BUILD_NORMAL
    purge_build.install_dest_exists.return_value = tmp_path / "install"
    mock_build_cls.get_build_list.return_value = [purge_build]
    purge(MagicMock(), make_purge_parsed(force=False))
    purge_build.purge.assert_not_called()
    purge_build.purge_install.assert_not_called()
    assert mock_confirm.call_count == 2


@patch("fprime.fbuild.cli.confirm", return_value=True)
@patch("fprime.fbuild.cli.Build")
def test_purge_confirm_accepted(mock_build_cls, mock_confirm, tmp_path):
    """purge without --force purges when the user confirms"""
    purge_build = MagicMock()
    purge_build.build_dir = tmp_path
    purge_build.build_type = BuildType.BUILD_NORMAL
    purge_build.install_dest_exists.return_value = None
    mock_build_cls.get_build_list.return_value = [purge_build]
    purge(MagicMock(), make_purge_parsed(force=False))
    purge_build.purge.assert_called_once()
    purge_build.purge_install.assert_not_called()
