"""Deprecated alias — moved to fprime.cli.fpp."""

import sys

import fprime.cli.fpp as _target

sys.modules[__name__] = _target
