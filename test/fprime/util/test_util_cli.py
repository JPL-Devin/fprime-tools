"""
Tests for fprime.cli.entry argument parsing and dispatch
"""

import pytest
from unittest.mock import MagicMock, patch

from fprime.cli.entry import parse_args, utility_entry


def test_parse_args_generate_cmake_args():
    """Tests that -D arguments to generate are collected as cmake arguments"""
    parsed, cmake_args, make_args, _, runners = parse_args(
        ["generate", "-DCMAKE_BUILD_TYPE=Debug", "-DFPRIME_SOME:BOOL=ON"]
    )
    assert parsed.command == "generate"
    assert cmake_args == {"CMAKE_BUILD_TYPE": "Debug", "FPRIME_SOME:BOOL": "ON"}
    assert make_args == {}
    assert "generate" in runners


def test_parse_args_build_jobs():
    """Tests that --jobs is turned into a make argument for build targets"""
    parsed, cmake_args, make_args, _, _ = parse_args(["build", "--jobs", "4"])
    assert parsed.command == "build"
    assert cmake_args == {}
    assert make_args == {"--jobs": 4}


def test_parse_args_unknown_argument_rejected(capsys):
    """Tests that unknown arguments exit with an error"""
    with pytest.raises(SystemExit) as exit_info:
        parse_args(["build", "--not-a-real-flag"])
    assert exit_info.value.code == 1
    assert "supplied invalid arguments" in capsys.readouterr().out


def test_parse_args_no_command_rejected(capsys):
    """Tests that a missing sub-command exits with an error"""
    with pytest.raises(SystemExit) as exit_info:
        parse_args([])
    assert exit_info.value.code == 1
    assert "not supplied sub-command" in capsys.readouterr().out


def test_parse_args_new_phased_requires_deployment(capsys):
    """Tests that new --phased without --deployment is rejected"""
    with pytest.raises(SystemExit) as exit_info:
        parse_args(["new", "--component", "--phased"])
    assert exit_info.value.code == 1
    assert "--phased option only works with --deployment" in capsys.readouterr().out


def test_utility_entry_dispatches_to_runner():
    """Tests that utility_entry loads a build and dispatches to the command runner"""
    build = MagicMock()
    with patch("fprime.cli.entry.load_build", return_value=build) as mock_load:
        with patch("fprime.cli.entry.parse_args") as mock_parse:
            runner = MagicMock(return_value=0)
            parsed = MagicMock()
            parsed.command = "build"
            mock_parse.return_value = (parsed, {}, {}, MagicMock(), {"build": runner})
            assert utility_entry(["build"]) == 0
    mock_load.assert_called_once()
    assert runner.call_args.args[0] is build


def test_utility_entry_version_check_skips_build_loading():
    """Tests that version-check does not load a build object"""
    with patch("fprime.cli.entry.load_build") as mock_load:
        with patch("fprime.cli.entry.parse_args") as mock_parse:
            runner = MagicMock(return_value=0)
            parsed = MagicMock()
            parsed.command = "version-check"
            mock_parse.return_value = (
                parsed,
                {},
                {},
                MagicMock(),
                {"version-check": runner},
            )
            assert utility_entry(["version-check"]) == 0
    mock_load.assert_not_called()
    assert runner.call_args.args[0] is None


def test_utility_entry_error_returns_one(capsys):
    """Tests that runner exceptions are reported on stderr with exit status 1"""
    with patch("fprime.cli.entry.load_build", return_value=MagicMock()):
        with patch("fprime.cli.entry.parse_args") as mock_parse:
            runner = MagicMock(side_effect=ValueError("bad input"))
            parsed = MagicMock()
            parsed.command = "build"
            parsed.verbose = False
            mock_parse.return_value = (parsed, {}, {}, MagicMock(), {"build": runner})
            assert utility_entry(["build"]) == 1
    assert "[ERROR] ValueError: bad input" in capsys.readouterr().err
