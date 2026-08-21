"""
Tests for fprime.fpp.cli
"""

from argparse import Namespace
from unittest.mock import MagicMock, patch

from fprime.fpp.cli import run_fpp_check, run_fpp_to_dict


@patch("fprime.fpp.cli.FppUtility")
def test_run_fpp_check_propagates_return_code(mock_utility):
    """Test run_fpp_check returns the return value of FppUtility.execute"""
    mock_utility.return_value.execute.return_value = 1
    parsed = Namespace(path="/some/path", unconnected=None)
    result = run_fpp_check(MagicMock(), parsed, {}, {}, [])
    assert result == 1


@patch("fprime.fpp.cli.FppUtility")
def test_run_fpp_check_propagates_success(mock_utility):
    """Test run_fpp_check returns zero when FppUtility.execute succeeds"""
    mock_utility.return_value.execute.return_value = 0
    parsed = Namespace(path="/some/path", unconnected=None)
    result = run_fpp_check(MagicMock(), parsed, {}, {}, [])
    assert result == 0


@patch("fprime.fpp.cli.FppUtility")
def test_run_fpp_to_dict_propagates_return_code(mock_utility):
    """Test run_fpp_to_dict returns the return value of FppUtility.execute"""
    mock_utility.return_value.execute.return_value = 2
    parsed = Namespace(path="/some/path", directory=None, size=None)
    result = run_fpp_to_dict(MagicMock(), parsed, {}, {}, [])
    assert result == 2
