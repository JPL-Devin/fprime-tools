"""Deprecated alias — moved to fprime.cli.build_helper."""

import sys

import fprime.cli.build_helper as _target

sys.modules[__name__] = _target
