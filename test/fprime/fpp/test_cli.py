"""Tests that fpp CLI runners propagate the exit status of the underlying utility"""

import argparse
from unittest import mock

from fprime.cli.fpp import run_fpp_check, run_fpp_to_dict


def _namespace(**kwargs):
    defaults = {"path": ".", "unconnected": None, "directory": None, "size": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_run_fpp_check_propagates_return_code():
    with mock.patch("fprime.cli.fpp.FppUtility") as utility:
        utility.return_value.execute.return_value = 3
        assert run_fpp_check(None, _namespace(), {}, {}, []) == 3


def test_run_fpp_check_propagates_success():
    with mock.patch("fprime.cli.fpp.FppUtility") as utility:
        utility.return_value.execute.return_value = 0
        assert run_fpp_check(None, _namespace(), {}, {}, []) == 0


def test_run_fpp_to_dict_propagates_return_code():
    with mock.patch("fprime.cli.fpp.FppUtility") as utility:
        utility.return_value.execute.return_value = 2
        assert run_fpp_to_dict(None, _namespace(), {}, {}, []) == 2
