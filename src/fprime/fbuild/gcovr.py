"""Deprecated alias — moved to fprime.build.targets.gcovr."""

import sys

import fprime.build.targets.gcovr as _target

sys.modules[__name__] = _target
