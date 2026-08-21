"""Deprecated alias — moved to fprime.build.settings."""

import sys

import fprime.build.settings as _target

sys.modules[__name__] = _target
