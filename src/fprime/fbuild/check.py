"""Deprecated alias — moved to fprime.build.targets.check."""

import sys

import fprime.build.targets.check as _target

sys.modules[__name__] = _target
