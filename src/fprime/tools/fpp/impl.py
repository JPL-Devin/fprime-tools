"""fprime.tools.fpp.impl: Command line targets for `fprime-util impl`

Processing and CLI entry points for `fprime-util impl` command line tool.

@author thomas-bc
"""

import argparse
import glob
import os
import tempfile
from pathlib import Path

from typing import TYPE_CHECKING, Callable, Dict, List, Tuple

from fprime.common.error import FprimeException
from fprime.build.builder import Build

from fprime.tools.fpp import merge
from fprime.tools.fpp.common import FppUtility
from fprime.tools.clang_format import ClangFormatter
from fprime.constants import UT_FILES_TARGET_PATH, UT_TEMPLATE_FILE_SUFFIX


class ExperimentalFeatureError(FprimeException):
    """Raised when an experimental feature is used without --accept-experimental"""


def _apply_clang_formatting(
    build: Build,
    framework_path: Path,
    files_dir: Path,
    generated_file_names: list[Path],
):
    """
    Format files if clang-format is available.

    Args:
        framework_path: F Prime framework path
        files_dir: Folder with generated files
        generated_file_names: List of generated file names
    """

    format_file = framework_path / ".clang-format"
    if format_file.is_file():
        clang_formatter = ClangFormatter("clang-format", format_file, {"backup": False})
        if clang_formatter.is_supported():
            for file_name in generated_file_names:
                clang_formatter.stage_file(files_dir / file_name)
            clang_formatter.execute(build, None, ({}, []))
    else:
        print(
            f"[INFO] .clang-format file not found at {format_file.resolve()}. Skipping formatting."
        )


def _move_ut_templates(files_dir, generated_file_names):
    """
    Move generated UT templates into "files_dir/<UT_FILES_TARGET_PATH>".
    The UT_TEMPLATE_FILE_SUFFIX is added into a file name unless it is already present.

    Args:
        files_dir: Folder with generated files
        generated_file_names: List of generated file names
    """
    # Create the UT folder
    ut_path = files_dir / Path(*UT_FILES_TARGET_PATH)
    ut_path.mkdir(parents=True, exist_ok=True)

    # Move the generated files
    for file_name in generated_file_names:
        source_path = files_dir / file_name
        destination_file_name = (
            file_name.with_suffix(UT_TEMPLATE_FILE_SUFFIX + file_name.suffix)
            if UT_TEMPLATE_FILE_SUFFIX not in file_name.suffixes
            else file_name
        )
        destination_path = ut_path / destination_file_name
        source_path.rename(destination_path)


def fpp_generate_implementation(
    build: Build,
    output_dir: Path,
    context: Path,
    apply_formatting: bool,
    generate_ut: bool,
    generate_test_helpers: bool = False,
    overwrite: bool = False,
    auto_merge: bool = False,
) -> int:
    """
    Generate implementation files from FPP templates.

    Args:
        build: Build object
        output_dir: The directory where the generated files will be written
        context: The path to the F´ module to generate files for
        apply_formatting: Whether to format the generated files using clang-format
        generate_ut: Generates UT files if set to True
        generate_test_helpers: Generate of test helper code if set to True
        overwrite: Overwrite existing implementation files if set to True
        auto_merge: Merge generated templates into existing hand files if set to True
    """

    prefixes = [
        *build.get_source_locations(),
        *build.get_build_cache_locations(),
    ]

    # Holds the list of generated files to be passed to clang-format
    gen_files = tempfile.NamedTemporaryFile(prefix="fprime-impl-")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Run fpp-to-cpp --template
    FppUtility("fpp-to-cpp", imports_as_sources=False).execute(
        build,
        context,
        args=(
            {},
            [
                "--template",
                *(["--unit-test"] if generate_ut else []),
                *(["--auto-test-helpers"] if not generate_test_helpers else []),
                "--names",
                gen_files.name,
                "--directory",
                str(output_dir),
                "--path-prefixes",
                ",".join(map(str, prefixes)),
            ],
        ),
    )

    framework_path = build.settings.get("framework_path", Path("."))
    # FPP --names outputs a list of file names.
    generated_file_names = [
        Path(line.decode("utf-8").strip()) for line in gen_files.readlines()
    ]

    if apply_formatting:
        _apply_clang_formatting(build, framework_path, output_dir, generated_file_names)

    annotate_failures = 0
    if generate_ut:
        _move_ut_templates(output_dir, generated_file_names)
    elif auto_merge:
        # Markers/hashes are only injected on --auto-merge runs (experimental).
        annotate_failures = _annotate_impl_templates(output_dir)

    if overwrite:
        file_list = glob.glob(f"{output_dir}/*.template.*pp", recursive=False)
        for filename in file_list:
            new_filename = filename.replace(".template", "")
            os.rename(filename, new_filename)
    elif auto_merge:
        return 1 if (_auto_merge_impl_templates(output_dir) or annotate_failures) else 0

    return 0


def _annotate_impl_templates(output_dir: Path) -> int:
    """Inject section end markers (and HPP section hashes) into impl templates.

    Returns the number of templates that could not be annotated.
    """
    failures = 0
    for path, with_hash in [
        (path, path.suffix == ".hpp")
        for path in sorted(Path(output_dir).glob("*.template.hpp"))
        + sorted(Path(output_dir).glob("*.template.cpp"))
    ]:
        try:
            merge.annotate_file(path, with_hash=with_hash)
        except (OSError, UnicodeError, merge.ImplMergeError) as error:
            print(f"[WARNING] Could not annotate {path.name}: {error}")
            failures += 1
    return failures


def _auto_merge_impl_templates(output_dir: Path) -> int:
    """Merge generated impl templates into existing hand files where present.

    Returns non-zero when any component's merge was skipped or aborted.
    """
    failures = 0
    hpp_templates = sorted(Path(output_dir).glob("*.template.hpp"))
    for template_cpp_path in Path(output_dir).glob("*.template.cpp"):
        if not template_cpp_path.with_name(
            template_cpp_path.name.replace(".template.cpp", ".template.hpp")
        ).exists():
            print(
                f"[WARNING] No matching template HPP for {template_cpp_path.name}; "
                "skipping auto merge."
            )
            failures += 1
    for template_hpp in hpp_templates:
        template_cpp = template_hpp.with_name(
            template_hpp.name.replace(".template.hpp", ".template.cpp")
        )
        if not template_cpp.exists():
            print(
                f"[WARNING] No matching {template_cpp.name} for {template_hpp.name}; "
                "skipping auto merge."
            )
            failures += 1
            continue
        target_hpp = template_hpp.with_name(template_hpp.name.replace(".template", ""))
        target_cpp = template_cpp.with_name(template_cpp.name.replace(".template", ""))
        if not merge.perform_auto_merge(
            template_hpp, template_cpp, target_hpp, target_cpp
        ):
            failures += 1
    return 1 if failures else 0


def run_fpp_impl(
    build: Build,
    parsed: argparse.Namespace,
    _: Dict[str, str],
    __: Dict[str, str],
    ___: List[str],
):
    """

    Args:
        build: build object
        parsed: parsed input arguments
        _: unused cmake_args
        __: unused make_args
        ___: unused pass-through arguments
    """

    if parsed.auto_merge and not parsed.accept_experimental:
        raise ExperimentalFeatureError(
            "--auto-merge is an experimental feature and requires --accept-experimental"
        )

    if parsed.ut and parsed.auto_merge:
        print("[WARNING] --auto-merge has no effect with --ut; ignoring --auto-merge.")

    return fpp_generate_implementation(
        build,
        Path(parsed.output_dir),
        Path(parsed.path),
        not parsed.no_format,
        parsed.ut,
        parsed.generate_test_helpers,
        parsed.overwrite,
        parsed.auto_merge and not parsed.ut,
    )


def add_fpp_impl_parsers(
    subparsers, common: argparse.ArgumentParser
) -> Tuple[Dict[str, Callable], Dict[str, argparse.ArgumentParser]]:
    """Sets up the fprime-viz command line parsers

    Creates command line parsers for fprime-viz commands and associates these commands to processing
    functions for those fpp commands.

    Args:
        subparsers: subparsers to add to
        common: common parser for all fprime-util commands

    Returns:
        Tuple of dictionary mapping command name to processor, and command to parser
    """
    impl_parser = subparsers.add_parser(
        "impl",
        help="Generate implementation templates",
        parents=[common],
        add_help=False,
    )
    impl_parser.add_argument(
        "--output-dir",
        help="Directory to generate files in. Default: cwd",
        required=False,
        default=os.getcwd(),
    )
    impl_parser.add_argument(
        "--no-format",
        action="store_true",
        help="Disable formatting (using clang-format) of generated files",
        required=False,
    )
    impl_parser.add_argument(
        "--generate-test-helpers",
        action="store_true",
        default=False,
        help="Generate test helper code for hand-coding. Default to False, leveraging the test helpers autocoded by FPP.",
        required=False,
    )
    write_group = impl_parser.add_mutually_exclusive_group()
    write_group.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Overwrite contents of current CPP and HPP files. Use with caution.",
        required=False,
    )
    write_group.add_argument(
        "--auto-merge",
        action="store_true",
        default=False,
        help="[EXPERIMENTAL] Merge generated templates into existing CPP and HPP files. "
        "New function stubs are added; hand-edited HPP sections abort the merge with a "
        "warning. Has no effect with --ut. Requires --accept-experimental.",
        required=False,
    )
    impl_parser.add_argument(
        "--accept-experimental",
        action="store_true",
        default=False,
        help="Acknowledge use of experimental features (required by --auto-merge).",
        required=False,
    )
    return {"impl": run_fpp_impl}, {"impl": impl_parser}
