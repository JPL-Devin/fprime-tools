"""Deprecated alias — moved to fprime.build.targets.target."""

import sys

import fprime.build.targets.target as _target

sys.modules[__name__] = _target
