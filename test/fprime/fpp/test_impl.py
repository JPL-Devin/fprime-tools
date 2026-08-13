"""
Tests for fprime.fpp.impl CLI gating (experimental --auto-merge).
"""

import argparse

import pytest

from fprime.fpp import impl


def _parsed(**overrides):
    defaults = {
        "auto_merge": False,
        "accept_experimental": False,
        "overwrite": False,
        "ut": False,
        "generate_test_helpers": False,
        "output_dir": ".",
        "path": ".",
        "no_format": True,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_auto_merge_requires_accept_experimental():
    with pytest.raises(impl.ExperimentalFeatureError):
        impl.run_fpp_impl(None, _parsed(auto_merge=True), {}, {}, [])


def test_auto_merge_allowed_with_accept_experimental(monkeypatch):
    called = {}

    def fake_generate(*args, **kwargs):
        called["ok"] = True
        return 0

    monkeypatch.setattr(impl, "fpp_generate_implementation", fake_generate)
    result = impl.run_fpp_impl(
        None, _parsed(auto_merge=True, accept_experimental=True), {}, {}, []
    )
    assert result == 0
    assert called.get("ok")


def test_accept_experimental_flag_registered():
    subparsers = argparse.ArgumentParser().add_subparsers()
    common = argparse.ArgumentParser(add_help=False)
    _, parsers = impl.add_fpp_impl_parsers(subparsers, common)
    parsed = parsers["impl"].parse_args(["--auto-merge", "--accept-experimental"])
    assert parsed.auto_merge and parsed.accept_experimental
    help_text = parsers["impl"].format_help()
    assert "EXPERIMENTAL" in help_text
