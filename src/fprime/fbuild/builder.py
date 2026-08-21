"""Deprecated alias -- moved to fprime.build.builder."""

import sys

import fprime.build.builder as _module

sys.modules[__name__] = _module
