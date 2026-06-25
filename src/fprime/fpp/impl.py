"""fprime.fpp.impl: Command line targets for `fprime-util impl`

Processing and CLI entry points for `fprime-util impl` command line tool.

@author thomas-bc
"""

import argparse
import glob
import os
import tempfile
from pathlib import Path

from typing import TYPE_CHECKING, Callable, Dict, List, Tuple

from fprime.fbuild.builder import Build

from fprime.fpp.common import FppUtility
from fprime.fpp import impl_merge
from fprime.util.code_formatter import ClangFormatter
from fprime.constants import UT_FILES_TARGET_PATH, UT_TEMPLATE_FILE_SUFFIX

# Suffixes used by fpp-to-cpp for generated implementation templates
_TEMPLATE_HPP_SUFFIX = ".template.hpp"
_TEMPLATE_CPP_SUFFIX = ".template.cpp"


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
        auto_merge: Merge newly generated members into existing implementation
            files instead of writing standalone *.template.* files
    """

    prefixes = [
        *build.get_source_locations(),
        *build.get_build_cache_locations(),
    ]

    # Holds the list of generated files to be passed to clang-format
    gen_files = tempfile.NamedTemporaryFile(prefix="fprime-impl-")

    output_dir.mkdir(parents=True, exist_ok=True)

    # When auto-merging, generate the templates into a scratch directory so they
    # do not clobber the user's existing implementation files. The new members
    # are then spliced into those files.
    merge_tmp = (
        tempfile.TemporaryDirectory(prefix="fprime-impl-merge-") if auto_merge else None
    )
    gen_dir = Path(merge_tmp.name) if merge_tmp is not None else output_dir

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
                str(gen_dir),
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

    if auto_merge:
        try:
            return _auto_merge_templates(
                build,
                framework_path,
                gen_dir,
                output_dir,
                generated_file_names,
                apply_formatting,
            )
        finally:
            merge_tmp.cleanup()

    if apply_formatting:
        _apply_clang_formatting(build, framework_path, output_dir, generated_file_names)

    if generate_ut:
        _move_ut_templates(output_dir, generated_file_names)

    if overwrite:
        file_list = glob.glob(f"{output_dir}/*.template.*pp", recursive=False)
        for filename in file_list:
            new_filename = filename.replace(".template", "")
            os.rename(filename, new_filename)

    return 0


def _auto_merge_templates(
    build: Build,
    framework_path: Path,
    gen_dir: Path,
    output_dir: Path,
    generated_file_names: List[Path],
    apply_formatting: bool,
) -> int:
    """
    Merge newly generated implementation templates into the user's existing
    implementation files.

    For each ``<Name>.template.hpp`` / ``<Name>.template.cpp`` pair generated in
    ``gen_dir``, splice any new member functions into ``<Name>.hpp`` /
    ``<Name>.cpp`` in ``output_dir``. If the user file does not yet exist, the
    generated template is written out as-is (first-time generation).

    Args:
        build: Build object (for clang-format)
        framework_path: F´ framework path (for the .clang-format file)
        gen_dir: Directory holding the freshly generated *.template.* files
        output_dir: Directory holding the user's implementation files
        generated_file_names: Names of the generated files
        apply_formatting: Whether to clang-format the merged files

    Returns:
        0 on success, 1 if any file could not be merged
    """
    # Collect component stems that have a generated template in gen_dir.
    stems = sorted(
        {
            name.name[: -len(_TEMPLATE_HPP_SUFFIX)]
            for name in generated_file_names
            if name.name.endswith(_TEMPLATE_HPP_SUFFIX)
        }
    )

    if not stems:
        print("[WARNING] No implementation templates were generated to merge.")
        return 0

    formatted_files: List[Path] = []
    had_error = False

    for stem in stems:
        for suffix, merge_fn in (
            (".hpp", impl_merge.merge_hpp),
            (".cpp", impl_merge.merge_cpp),
        ):
            template_path = gen_dir / f"{stem}.template{suffix}"
            user_path = output_dir / f"{stem}{suffix}"
            if not template_path.is_file():
                continue

            template_text = template_path.read_text(encoding="utf-8")

            # First-time generation: no user file yet, just write the template.
            if (
                not user_path.is_file()
                or not user_path.read_text(encoding="utf-8").strip()
            ):
                user_path.write_text(template_text, encoding="utf-8")
                formatted_files.append(Path(user_path.name))
                print(f"[INFO] Created {user_path}")
                continue

            user_text = user_path.read_text(encoding="utf-8")
            try:
                result = merge_fn(template_text, user_text, stem)
            except Exception as exc:  # pragma: no cover - defensive
                print(f"[ERROR] Failed to merge {user_path}: {exc}")
                had_error = True
                continue

            for name in result.drifted:
                print(
                    f"[WARNING] Signature of '{name}' in {user_path} differs from "
                    "the model. The implementation was left unchanged; please "
                    "update it by hand."
                )

            if result.text is None:
                print(f"[INFO] {user_path} is up to date, nothing to merge.")
                continue

            user_path.write_text(result.text, encoding="utf-8")
            formatted_files.append(Path(user_path.name))
            added = ", ".join(result.added) if result.added else "no new members"
            print(f"[INFO] Merged into {user_path}: {added}")
            for include in result.added_includes:
                print(f"[INFO]   added include: {include}")

    if apply_formatting and formatted_files:
        _apply_clang_formatting(build, framework_path, output_dir, formatted_files)

    return 1 if had_error else 0


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

    if parsed.overwrite and parsed.auto_merge:
        print("[ERROR] --overwrite and --auto-merge cannot be used together.")
        return 1

    if parsed.auto_merge and parsed.ut:
        print(
            "[ERROR] --auto-merge is not supported with --ut. The unit-test "
            "templates (Tester/TestMain) are not component implementation files "
            "and are not merged."
        )
        return 1

    return fpp_generate_implementation(
        build,
        Path(parsed.output_dir),
        Path(parsed.path),
        not parsed.no_format,
        parsed.ut,
        parsed.generate_test_helpers,
        parsed.overwrite,
        parsed.auto_merge,
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
    impl_parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Overwrite contents of current CPP and HPP files. Use with caution.",
        required=False,
    )
    impl_parser.add_argument(
        "--auto-merge",
        action="store_true",
        default=False,
        help="Merge newly generated members (handlers, command handlers, etc.) "
        "into the existing CPP and HPP files instead of writing standalone "
        "*.template.* files. Existing implementations are left untouched. "
        "Cannot be combined with --overwrite.",
        required=False,
    )
    return {"impl": run_fpp_impl}, {"impl": impl_parser}
