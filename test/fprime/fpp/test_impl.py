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
        called["args"] = args
        return 0

    monkeypatch.setattr(impl, "fpp_generate_implementation", fake_generate)
    result = impl.run_fpp_impl(
        None, _parsed(auto_merge=True, accept_experimental=True), {}, {}, []
    )
    assert result == 0
    assert called["args"][-1] is True  # auto_merge propagated


def test_auto_merge_ignored_with_ut(monkeypatch):
    called = {}

    def fake_generate(*args, **kwargs):
        called["args"] = args
        return 0

    monkeypatch.setattr(impl, "fpp_generate_implementation", fake_generate)
    impl.run_fpp_impl(
        None, _parsed(auto_merge=True, accept_experimental=True, ut=True), {}, {}, []
    )
    assert called["args"][-1] is False  # auto_merge actually ignored with --ut


def test_accept_experimental_flag_registered():
    subparsers = argparse.ArgumentParser().add_subparsers()
    common = argparse.ArgumentParser(add_help=False)
    _, parsers = impl.add_fpp_impl_parsers(subparsers, common)
    parsed = parsers["impl"].parse_args(["--auto-merge", "--accept-experimental"])
    assert parsed.auto_merge and parsed.accept_experimental
    help_text = parsers["impl"].format_help()
    assert "EXPERIMENTAL" in help_text


def test_overwrite_and_auto_merge_mutually_exclusive():
    subparsers = argparse.ArgumentParser().add_subparsers()
    common = argparse.ArgumentParser(add_help=False)
    _, parsers = impl.add_fpp_impl_parsers(subparsers, common)
    with pytest.raises(SystemExit):
        parsers["impl"].parse_args(["--auto-merge", "--overwrite"])


def test_auto_merge_templates_lone_hpp_creates_no_targets(tmp_path, capsys):
    (tmp_path / "Comp.template.hpp").write_text("class Comp {\n};\n")
    result = impl._auto_merge_impl_templates(tmp_path)
    assert result != 0
    assert not (tmp_path / "Comp.hpp").exists()
    assert "skipping auto merge" in capsys.readouterr().out


def test_auto_merge_templates_lone_cpp_warns(tmp_path, capsys):
    (tmp_path / "Comp.template.cpp").write_text("namespace M {\n}\n")
    result = impl._auto_merge_impl_templates(tmp_path)
    assert result != 0
    assert not (tmp_path / "Comp.cpp").exists()
    assert "No matching template HPP" in capsys.readouterr().out
