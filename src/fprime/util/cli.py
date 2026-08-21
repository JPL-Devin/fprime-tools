"""Deprecated alias -- moved to fprime.cli.entry."""

import sys

import fprime.cli.entry as _module

sys.modules[__name__] = _module
