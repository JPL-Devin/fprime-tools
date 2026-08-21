"""Deprecated alias — moved to fprime.build.cmake."""

import sys

import fprime.build.cmake as _target

sys.modules[__name__] = _target
