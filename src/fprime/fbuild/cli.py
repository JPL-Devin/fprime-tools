"""Deprecated alias -- moved to fprime.cli.fbuild."""

import sys

import fprime.cli.fbuild as _module

sys.modules[__name__] = _module
