"""Deprecated alias — moved to fprime.cli.commands."""

import sys

import fprime.cli.commands as _target

sys.modules[__name__] = _target
