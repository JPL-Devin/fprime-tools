"""Deprecated alias -- moved to fprime.tools.fpp.impl."""

import sys

import fprime.tools.fpp.impl as _module

sys.modules[__name__] = _module
