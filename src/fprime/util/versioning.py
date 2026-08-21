"""Deprecated alias -- moved to fprime.cli.versioning."""

import sys

import fprime.cli.versioning as _module

sys.modules[__name__] = _module
