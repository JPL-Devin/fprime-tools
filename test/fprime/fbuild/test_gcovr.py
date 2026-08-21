"""
Tests for the Gcovr coverage action argument construction
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from fprime.build.targets.gcovr import Gcovr
from fprime.build.targets.target import TargetScope

ALL_OPTIONS = [
    "--all-sources",
    "--comp-ac",
    "--port-ac",
    "--type-ac",
    "--test-ac",
    "--sm-ac",
    "--test-sources",
]


def _make_builder(tmp_path, settings=None):
    """Build a mock builder rooted at tmp_path"""
    settings = settings if settings is not None else {}
    builder = MagicMock()
    builder.build_dir = tmp_path / "build-fprime-automatic-native"
    builder.build_dir.mkdir(exist_ok=True)
    builder.get_settings.side_effect = lambda key, default=None: settings.get(
        key, default
    )
    builder.settings = {}
    builder.is_project_root.return_value = True
    builder.cmake.verbose = False
    return builder


def _run_gcovr(tmp_path, builder, make_args=None, pass_through=None, options=None):
    """Run Gcovr.execute with mocked subprocess and return the argv it was given"""
    options = {option: False for option in ALL_OPTIONS} | (options or {})
    gcovr = Gcovr(TargetScope.GLOBAL)
    with patch(
        "fprime.build.targets.gcovr.shutil.which", return_value="/usr/bin/gcovr"
    ):
        with patch(
            "fprime.build.targets.gcovr.subprocess.call", return_value=0
        ) as mock_call:
            gcovr.execute(
                builder, tmp_path, (make_args or {}, pass_through or [], options)
            )
    return mock_call.call_args.args[0]


def test_gcovr_default_arguments(tmp_path):
    """Tests the default gcovr invocation: root, cache, exclusions, and outputs"""
    settings = {"project_root": tmp_path, "framework_path": tmp_path / "fprime"}
    builder = _make_builder(tmp_path, settings)
    argv = _run_gcovr(tmp_path, builder)

    resolved_root = str(Path(tmp_path).resolve())
    assert argv[:4] == [
        "gcovr",
        "-r",
        resolved_root,
        str(builder.build_dir.resolve()),
    ]
    joined = " ".join(argv)
    assert "ComponentAc.[ch]pp" in joined, "Autocode exclusions missing"
    assert ".*/test/.*" in argv, "Test source exclusion missing"
    assert "--exclude-throw-branches" in argv
    assert "--exclude-branches-by-pattern" in argv, "FW_ASSERT exclusion missing"
    framework_resolved = str((tmp_path / "fprime").resolve())
    assert f"{framework_resolved}/Autocoders" in argv
    assert "--print-summary" in argv
    assert str(tmp_path.resolve() / "coverage" / "summary.txt") in argv


def test_gcovr_options_and_pass_through(tmp_path):
    """Tests that inclusion options, jobs, and pass-through arguments are honored"""
    builder = _make_builder(tmp_path, {"project_root": tmp_path})
    argv = _run_gcovr(
        tmp_path,
        builder,
        make_args={"--jobs": 4},
        pass_through=["--xml", "out.xml"],
        options={
            "--all-sources": True,
            "--enable-fw-assert-branch-coverage": True,
        },
    )
    joined = " ".join(argv)
    assert "ComponentAc.[ch]pp" not in joined, "--all-sources should drop exclusions"
    assert ".*/test/.*" not in argv, "--all-sources should include test sources"
    assert "--exclude-branches-by-pattern" not in argv
    assert argv[4:6] == ["-j", "4"]
    assert argv[-2:] == ["--xml", "out.xml"]


def test_gcovr_project_root_fallback(tmp_path):
    """Tests fallback to framework path then build-cache parent for project root"""
    framework = tmp_path / "fprime"
    builder = _make_builder(tmp_path, {"framework_path": framework})
    argv = _run_gcovr(tmp_path, builder)
    assert argv[2] == str(framework.resolve())

    builder = _make_builder(tmp_path, {})
    argv = _run_gcovr(tmp_path, builder)
    assert argv[2] == str(tmp_path.resolve())
