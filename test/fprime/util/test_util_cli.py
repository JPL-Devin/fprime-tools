"""
Tests for fprime.cli.entry: argument parsing and command dispatch
"""

from unittest.mock import MagicMock, patch

import pytest

from fprime.build.builder import UnableToDetectProjectException
from fprime.cli.entry import parse_args, utility_entry


@pytest.mark.parametrize(
    "args,command",
    [
        (["generate"], "generate"),
        (["purge"], "purge"),
        (["build"], "build"),
        (["check"], "check"),
        (["info"], "info"),
        (["version-check"], "version-check"),
        (["new", "--component"], "new"),
        (["format"], "format"),
        (["hash-to-file", "0x123"], "hash-to-file"),
        (["fpp-check"], "fpp-check"),
        (["fpp-to-dict"], "fpp-to-dict"),
        (["impl"], "impl"),
        (["visualize"], "visualize"),
    ],
)
def test_parse_args_commands(args, command):
    """Every command parses with expected namespace and empty cmake/make args"""
    parsed, cmake_args, make_args, parser, runners = parse_args(args)
    assert parsed.command == command
    assert cmake_args == {}
    assert make_args == {}
    assert command in runners
    assert parsed.platform == "default"
    assert parsed.build_cache is None


def test_parse_args_hash_to_file_hash_value():
    """hash-to-file converts the hash argument via int(x, 0)"""
    parsed, _, _, _, _ = parse_args(["hash-to-file", "0x123"])
    assert parsed.hash == 0x123
    parsed, _, _, _, _ = parse_args(["hash-to-file", "291"])
    assert parsed.hash == 291


def test_parse_args_generate_d_flags():
    """-D<VAR>=<VALUE> arguments to generate become cmake_args"""
    parsed, cmake_args, make_args, _, _ = parse_args(
        ["generate", "-DFOO=BAR", "-DBAZ:STRING=QUX"]
    )
    assert parsed.command == "generate"
    assert cmake_args == {"FOO": "BAR", "BAZ:STRING": "QUX"}
    assert make_args == {}


def test_parse_args_jobs_to_make_args():
    """--jobs on build targets becomes a make argument"""
    parsed, cmake_args, make_args, _, _ = parse_args(["build", "--jobs", "4"])
    assert cmake_args == {}
    assert make_args == {"--jobs": 4}


def test_parse_args_unknown_argument_rejected():
    """Unknown arguments cause an argument validation exit"""
    with pytest.raises(SystemExit):
        parse_args(["build", "--this-does-not-exist"])


def test_parse_args_d_flags_rejected_outside_generate():
    """-D arguments are only consumed by generate"""
    with pytest.raises(SystemExit):
        parse_args(["build", "-DFOO=BAR"])


def test_parse_args_no_command_rejected():
    """Missing sub-command causes an argument validation exit"""
    with pytest.raises(SystemExit):
        parse_args([])


def test_parse_args_phased_requires_deployment():
    """--phased is only valid with --deployment"""
    with pytest.raises(SystemExit):
        parse_args(["new", "--component", "--phased"])


@patch("fprime.cli.entry.run_info")
@patch("fprime.cli.entry.load_build")
def test_utility_entry_dispatch(mock_load_build, mock_run_info):
    """utility_entry loads a build and dispatches to the selected runner"""
    mock_build = MagicMock()
    mock_load_build.return_value = mock_build
    mock_run_info.return_value = 0
    assert utility_entry(["info"]) == 0
    mock_load_build.assert_called_once()
    mock_run_info.assert_called_once()
    args, _ = mock_run_info.call_args
    assert args[0] is mock_build
    assert args[1].command == "info"
    assert args[2] == {}
    assert args[3] == {}
    assert args[4] == []


@patch("fprime.cli.entry.run_version_check")
@patch("fprime.cli.entry.load_build")
def test_utility_entry_version_check_skips_build(mock_load_build, mock_run_version):
    """version-check does not load a build"""
    mock_run_version.return_value = 0
    assert utility_entry(["version-check"]) == 0
    mock_load_build.assert_not_called()
    args, _ = mock_run_version.call_args
    assert args[0] is None


@patch("fprime.cli.entry.load_build")
def test_utility_entry_error_exit_code(mock_load_build, capsys):
    """utility_entry returns 1 when the project cannot be detected"""
    mock_load_build.side_effect = UnableToDetectProjectException()
    assert utility_entry(["build"]) == 1
    captured = capsys.readouterr()
    assert "[ERROR] Could not detect project directory" in captured.err


@patch("fprime.cli.entry.run_info")
@patch("fprime.cli.entry.load_build")
def test_utility_entry_runner_exit_code_propagated(mock_load_build, mock_run_info):
    """utility_entry propagates the runner's return code"""
    mock_run_info.return_value = 3
    assert utility_entry(["info"]) == 3
