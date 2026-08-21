"""Deprecated alias — moved to fprime.build.targets.enumerator."""

import sys

import fprime.build.targets.enumerator as _target

sys.modules[__name__] = _target
