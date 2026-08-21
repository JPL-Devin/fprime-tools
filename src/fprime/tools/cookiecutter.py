"""Cookie cutter wrapper used to template out components"""

import os
import sys

from typing import TYPE_CHECKING, Callable
from contextlib import contextmanager
from pathlib import Path

from cookiecutter.exceptions import OutputDirExistsException, UnknownRepoType
from cookiecutter.main import cookiecutter

from fprime.common.utils import confirm, check_path_is_within_fprime_module
from fprime.build.builder import Build
from fprime.build.cmake import CMakeExecutionException
from fprime.tools.fpp.impl import fpp_generate_implementation
from fprime.util.file_util import get_directory_path_relative_to_root

if TYPE_CHECKING:
    import argparse


def run_impl(build: Build, source_path: Path):
    """Run implementation of files in source_path"""
    if not confirm("Generate implementation files?"):
        return False
    print("Refreshing cache and generating implementation files...")

    with suppress_stdout():
        fpp_generate_implementation(
            build,
            source_path,
            source_path,
            apply_formatting=True,
            generate_ut=False,
            overwrite=True,
        )

    return True


@contextmanager
def suppress_stdout():
    with open(os.devnull, "w") as devnull:
        old_stdout = sys.stdout
        sys.stdout = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout


def find_nearest_cmake_file(component_dir: Path, cmake_root: Path, proj_root: Path):
    """Find the nearest CMake file, i.e. CMakeLists.txt or project.cmake

    The "nearest" file is defined as the closest parent that is not the project root CMakeLists.txt.
    If none is found, the same procedure is run from the deployment directory and includes the project
    root this time. If nothing is found, None is returned.

    In short the following in order of preference:
     - Any Component Parent
     - Any Deployment Parent
     - project.cmake
     - None

    Args:
        component_dir: directory of new component
        deployment: deployment directory
        proj_root: project root directory

    Returns:
        path to CMakeLists.txt or None
    """
    test_path = component_dir.parent
    # First iterate from where we are, then from the deployment to find the nearest CMakeList.txt nearby
    for test_path, end_path in [(test_path, proj_root), (cmake_root, proj_root.parent)]:
        while proj_root is not None and test_path != proj_root.parent:
            project_file = test_path / "project.cmake"
            if project_file.is_file():
                return project_file
            cmake_list_file = test_path / "CMakeLists.txt"
            if cmake_list_file.is_file():
                return cmake_list_file
            test_path = test_path.parent
    return None


def _new_from_template(
    build: Build,
    kind: str,
    builtin_template: str,
    settings_key: str = None,
    builtin_message: str = None,
    source: str = None,
    extra_context: Callable = None,
    cookiecutter_args: dict = None,
    register: bool = True,
    output_dir_exists_suffix: str = ". Use --overwrite to overwrite (will not delete non-generated files).",
    on_success: Callable = None,
):
    """Instantiate a cookiecutter template, register it with the build system, and handle errors"""
    try:
        if source is None and settings_key is not None:
            setting = build.get_settings(settings_key, None)
            if setting is not None and setting != "default":
                source = setting
                print(f"[INFO] Cookiecutter source: {source}")
        if source is None:
            source = (
                os.path.dirname(__file__)
                + "/../cookiecutter_templates/"
                + builtin_template
            )
            if builtin_message is not None:
                print(builtin_message)
        gen_path = Path(
            cookiecutter(
                source,
                extra_context=extra_context() if extra_context is not None else {},
                **(cookiecutter_args or {}),
            )
        ).resolve()
        if register:
            register_with_cmake(
                gen_path,
                (
                    build.get_settings("project_root", None) or build.cmake_root
                ).resolve(),
                build.cmake_root,
            )
        if on_success is not None:
            return on_success(gen_path)
        return 0
    except OutputDirExistsException as out_directory_error:
        print(f"{out_directory_error}{output_dir_exists_suffix}", file=sys.stderr)
    except UnknownRepoType:
        print(
            f"[ERROR] {source} is not a valid cookiecutter template. Please check the source and try again.",
            file=sys.stderr,
        )
    except CMakeExecutionException as exc:
        print(f"[ERROR] Failed to create {kind}. {exc}", file=sys.stderr)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
    except PermissionError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
    except OSError as ose:
        print(f"[ERROR] {ose}", file=sys.stderr)
    return 1


def new_component(build: Build, parsed_args: "argparse.Namespace"):
    """Uses cookiecutter for making new components"""

    if (
        check_path_is_within_fprime_module(path=Path.cwd(), is_component=True)
        and not parsed_args.force
    ):
        print(
            "[ERROR] Wrong location. Cannot create component within an existing component."
            " Use --force to override."
        )
        return 1

    def extra_context():
        proj_root = build.get_settings("project_root", None) or build.cmake_root
        # Use current working directory name as default namespace, unless at project root
        context = {}
        if not proj_root.samefile(Path.cwd()):
            cwd = Path.cwd()
            # If in default Components directory, use parent directory name, which should be the top level namespace directory
            context["component_namespace"] = (
                cwd.parent.name if cwd.name == "Components" else cwd.name
            )
        return context

    def on_success(gen_path: Path):
        # Attempt implementation
        if not run_impl(build, gen_path):
            print(
                f"[INFO] Did not generate implementations for {gen_path}. Please do so manually."
            )
            return 0
        print("[INFO] Created new component and generated initial implementations.")
        return 0

    return _new_from_template(
        build,
        kind="component",
        builtin_template="cookiecutter-fprime-component",
        settings_key="component_cookiecutter",
        builtin_message="[INFO] Cookiecutter source: using builtin",
        extra_context=extra_context,
        cookiecutter_args={"overwrite_if_exists": parsed_args.overwrite},
        output_dir_exists_suffix="",
        on_success=on_success,
    )


def new_deployment(build: Build, parsed_args: "argparse.Namespace"):
    """Creates a new deployment using cookiecutter"""

    if check_path_is_within_fprime_module(Path.cwd()) and not parsed_args.force:
        print(
            "[ERROR] Wrong location. Cannot create deployment within an existing component or deployment"
        )
        return 1

    if parsed_args.phased:
        builtin_template = "cookiecutter-fprime-deployment-phased"
        builtin_message = (
            "[INFO] Cookiecutter: using builtin phased template for new deployment"
        )
    else:
        builtin_template = "cookiecutter-fprime-deployment"
        builtin_message = (
            "[INFO] Cookiecutter: using builtin template for new deployment"
        )

    def extra_context():
        context = {}
        rel_path = get_directory_path_relative_to_root(build)
        if rel_path:
            context["__include_path_prefix"] = f"{rel_path}/"
        # Use current working directory name as default namespace, unless at project root
        project_root: Path = (
            build.get_settings("project_root", None) or build.cmake_root
        )
        if not project_root.samefile(Path.cwd()):
            context["deployment_namespace"] = Path.cwd().name
        return context

    def on_success(gen_path: Path):
        print(f"[INFO] New deployment successfully created: {gen_path}")
        return 0

    return _new_from_template(
        build,
        kind="deployment",
        builtin_template=builtin_template,
        settings_key="deployment_cookiecutter",
        builtin_message=builtin_message,
        extra_context=extra_context,
        cookiecutter_args={"overwrite_if_exists": parsed_args.overwrite},
        on_success=on_success,
    )


def new_subtopology(build: Build, parsed_args: "argparse.Namespace"):
    """Creates a new subtopology using cookiecutter"""

    def on_success(gen_path: Path):
        print(f"[INFO] New subtopology successfully created: {gen_path}")
        return 0

    return _new_from_template(
        build,
        kind="subtopology",
        builtin_template="cookiecutter-fprime-subtopology",
        settings_key="subtopology_cookiecutter",
        builtin_message="[INFO] Cookiecutter: using builtin template for new subtopology",
        cookiecutter_args={"overwrite_if_exists": parsed_args.overwrite},
        on_success=on_success,
    )


def new_module(build: Build, parsed_args: "argparse.Namespace", source=None):
    """Creates a new module using cookiecutter"""

    return _new_from_template(
        build,
        kind="module",
        builtin_template="cookiecutter-fprime-module",
        source=source,
        cookiecutter_args={
            "overwrite_if_exists": parsed_args.overwrite,
            "output_dir": parsed_args.path,
        },
    )


def new_rule_based_testing(build: Build, parsed_args: "argparse.Namespace"):
    """Creates a new rules based testing scaffold using cookiecutter"""

    cwd = Path.cwd()
    if cwd.name == "ut" and cwd.parent.name == "test":
        print(
            "[ERROR] Wrong location. Cannot be run from the test/ut directory."
            " Please navigate to the component directory and try again."
        )
        return 1

    def extra_context():
        context = {}
        rel_path = get_directory_path_relative_to_root(build)
        context["__include_path_prefix"] = f"{rel_path}" if rel_path else ""
        cwd = Path.cwd()
        context["_component_name"] = cwd.name
        context["_component_namespace"] = (
            cwd.parent.parent.name if cwd.parent.name == "Components" else cwd.name
        )
        print(context)
        return context

    def on_success(gen_path: Path):
        print(
            f"[INFO] Rule-based test scaffold successfully created in {gen_path}/test/ut/ \n"
            "[INFO] For next steps, refer to the F Prime How-To Guide on Rule-Based Testing"
        )
        return 0

    return _new_from_template(
        build,
        kind="rule-based testing",
        builtin_template="cookiecutter-fprime-rules-test",
        extra_context=extra_context,
        cookiecutter_args={
            "overwrite_if_exists": True,  # needed to add to existing test/ut directory
            "skip_if_file_exists": True,  # safety
        },
        register=False,
        on_success=on_success,
    )


def register_with_cmake(gen_path: Path, proj_root: Path, cmake_root: Path):
    cmake_file = find_nearest_cmake_file(gen_path, cmake_root, proj_root)
    if cmake_file is None or not add_to_cmake(
        cmake_file,
        gen_path.relative_to(cmake_file.parent),
        proj_root,
    ):
        print(
            f"[INFO] Could not register {gen_path} with build system. Please add it manually."
        )


def add_to_cmake(list_file: Path, comp_path: Path, project_root: Path = None):
    """Adds comp_path directory to CMakeLists.txt. If project_root is supplied,
    the logged path will be relative to the project root instead of absolute"""
    short_display_path = (
        list_file
        if project_root is None
        else project_root.name / list_file.relative_to(project_root)
    )
    print(f"[INFO] Found CMake file at '{short_display_path}'")
    with open(list_file, "r") as f:
        lines = f.readlines()

    addition = (
        'add_fprime_subdirectory("${CMAKE_CURRENT_LIST_DIR}/' + str(comp_path) + '/")\n'
    )
    if addition in lines:
        print("Already added to CMakeLists.txt")
        return True

    if not confirm(f"Add {comp_path} to {short_display_path} at end of file?"):
        return False

    # Handle case where the last line does not end with a newline
    if len(lines) > 0 and (not lines[-1].endswith("\n")):
        lines[-1] += "\n"

    lines.append(addition)
    with open(list_file, "w") as f:
        f.write("".join(lines))
    return True


def is_valid_name(word: str):
    if not isinstance(word, str):
        raise ValueError("Incorrect usage of is_valid_name")
    invalid_characters = [
        "#",
        "%",
        "&",
        "{",
        "}",
        "/",
        "\\",
        "<",
        ">",
        "*",
        "?",
        " ",
        "$",
        "!",
        "'",
        '"',
        ":",
        "@",
        "+",
        "`",
        "|",
        "=",
        "-",
    ]
    for char in invalid_characters:
        if char in word:
            return char
    return "valid"
