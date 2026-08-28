"""Deprecated alias — moved to fprime.tools.clang_format."""

import sys

import fprime.tools.clang_format as _target

sys.modules[__name__] = _target
