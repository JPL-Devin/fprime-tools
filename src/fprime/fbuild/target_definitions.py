"""Deprecated alias — moved to fprime.build.targets."""

import sys

import fprime.build.targets as _target

sys.modules[__name__] = _target
