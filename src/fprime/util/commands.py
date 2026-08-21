"""Deprecated alias -- moved to fprime.cli.commands."""

import sys

import fprime.cli.commands as _module

sys.modules[__name__] = _module
