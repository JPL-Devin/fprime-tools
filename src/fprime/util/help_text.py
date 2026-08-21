"""Deprecated alias -- moved to fprime.cli.help_text."""

import sys

import fprime.cli.help_text as _module

sys.modules[__name__] = _module
