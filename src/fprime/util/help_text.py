"""Deprecated alias — moved to fprime.cli.help_text."""

import sys

import fprime.cli.help_text as _target

sys.modules[__name__] = _target
