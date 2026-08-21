"""Cookie cutter wrapper used to template out components"""

import os
import sys

from typing import Optional, Tuple, TYPE_CHECKING
from contextlib import contextmanager
from pathlib import Path

from cookiecutter.exceptions import OutputDirExistsException, UnknownRepoType
from cookiecutter.main import cookiecutter

from fprime.common.utils import confirm, check_path_is_within_fprime_module
from fprime.fbuild.builder import Build
from fprime.fbuild.cmake import CMakeExecutionException
from fprime.fpp.impl import fpp_generate_implementation
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


def _project_root(build: Build) -> Path:
    """Project root setting, falling back to the cmake root"""
    return build.get_settings("project_root", None) or build.cmake_root


def _resolve_template_source(
    build: Build, setting_key: str, builtin_template: str, builtin_message: str
) -> str:
    """Resolve a cookiecutter template source: the settings.ini override or the builtin template

    Args:
        build: build object to read settings from
        setting_key: settings.ini key holding a template override
        builtin_template: name of the builtin template directory
        builtin_message: message printed when the builtin template is used

    Returns:
        cookiecutter template source
    """
    source = build.get_settings(setting_key, None)
    if source is not None and source != "default":
        print(f"[INFO] Cookiecutter source: {source}")
        return source
    print(builtin_message)
    return os.path.dirname(__file__) + f"/../cookiecutter_templates/{builtin_template}"


def _instantiate_template(
    build: Build,
    source: str,
    kind: str,
    extra_context: dict = None,
    register: bool = True,
    **cookiecutter_kwargs,
) -> Tuple[int, Optional[Path]]:
    """Run cookiecutter for a template source and register the result with the build system

    Args:
        build: build object used for build-system registration
        source: cookiecutter template source
        kind: object kind used in error messages (e.g. "component")
        extra_context: extra context handed to cookiecutter
        register: register the generated path with CMake. Default: True
        cookiecutter_kwargs: remaining keyword arguments handed to cookiecutter

    Returns:
        Tuple of (return code, generated path or None on failure)
    """
    try:
        gen_path = Path(
            cookiecutter(
                source, extra_context=extra_context or {}, **cookiecutter_kwargs
            )
        ).resolve()
        if register:
            register_with_cmake(
                gen_path, Path(_project_root(build)).resolve(), build.cmake_root
            )
        return 0, gen_path
    except OutputDirExistsException as out_directory_error:
        print(
            f"{out_directory_error}. Use --overwrite to overwrite (will not delete non-generated files).",
            file=sys.stderr,
        )
    except UnknownRepoType:
        print(
            f"[ERROR] {source} is not a valid cookiecutter template. Please check the source and try again.",
            file=sys.stderr,
        )
    except (FileNotFoundError, PermissionError) as error:
        print(f"[ERROR] {error}. Failed to write to the directory.", file=sys.stderr)
    except OSError as ose:
        print(f"[ERROR] {ose}", file=sys.stderr)
    except CMakeExecutionException as exc:
        print(f"[ERROR] Failed to create {kind}. {exc}", file=sys.stderr)
    return 1, None


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

    source = _resolve_template_source(
        build,
        "component_cookiecutter",
        "cookiecutter-fprime-component",
        "[INFO] Cookiecutter source: using builtin",
    )

    # Use current working directory name as default namespace, unless at project root
    extra_context = {}
    if not _project_root(build).samefile(Path.cwd()):
        cwd = Path.cwd()
        # If in default Components directory, use parent directory name, which should be the top level namespace directory
        extra_context["component_namespace"] = (
            cwd.parent.name if cwd.name == "Components" else cwd.name
        )

    code, gen_path = _instantiate_template(
        build,
        source,
        "component",
        extra_context=extra_context,
        overwrite_if_exists=parsed_args.overwrite,
    )
    if code != 0:
        return code
    # Attempt implementation
    if not run_impl(build, gen_path):
        print(
            f"[INFO] Did not generate implementations for {gen_path}. Please do so manually."
        )
        return 0
    print("[INFO] Created new component and generated initial implementations.")
    return 0


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
    source = _resolve_template_source(
        build, "deployment_cookiecutter", builtin_template, builtin_message
    )

    # Extra contextual information for cookiecutter
    extra_context = {}
    rel_path = get_directory_path_relative_to_root(build)
    if rel_path:
        extra_context["__include_path_prefix"] = f"{rel_path}/"
    # Use current working directory name as default namespace, unless at project root
    if not _project_root(build).samefile(Path.cwd()):
        extra_context["deployment_namespace"] = Path.cwd().name

    code, gen_path = _instantiate_template(
        build,
        source,
        "deployment",
        extra_context=extra_context,
        overwrite_if_exists=parsed_args.overwrite,
    )
    if code != 0:
        return code
    print(f"[INFO] New deployment successfully created: {gen_path}")
    return 0


def new_subtopology(build: Build, parsed_args: "argparse.Namespace"):
    """Creates a new subtopology using cookiecutter"""
    source = _resolve_template_source(
        build,
        "subtopology_cookiecutter",
        "cookiecutter-fprime-subtopology",
        "[INFO] Cookiecutter: using builtin template for new subtopology",
    )
    code, gen_path = _instantiate_template(
        build, source, "subtopology", overwrite_if_exists=parsed_args.overwrite
    )
    if code != 0:
        return code
    print(f"[INFO] New subtopology successfully created: {gen_path}")
    return 0


def new_module(build: Build, parsed_args: "argparse.Namespace", source=None):
    """Creates a new module using cookiecutter"""

    if source is None:
        source = (
            os.path.dirname(__file__)
            + "/../cookiecutter_templates/cookiecutter-fprime-module"
        )
    code, _ = _instantiate_template(
        build,
        source,
        "module",
        overwrite_if_exists=parsed_args.overwrite,
        output_dir=parsed_args.path,
    )
    return code


def new_rule_based_testing(build: Build, parsed_args: "argparse.Namespace"):
    """Creates a new rules based testing scaffold using cookiecutter"""

    cwd = Path.cwd()
    if cwd.name == "ut" and cwd.parent.name == "test":
        print(
            "[ERROR] Wrong location. Cannot be run from the test/ut directory."
            " Please navigate to the component directory and try again."
        )
        return 1

    source = (
        os.path.dirname(__file__)
        + "/../cookiecutter_templates/cookiecutter-fprime-rules-test"
    )
    # Extra contextual information for cookiecutter
    extra_context = {}
    rel_path = get_directory_path_relative_to_root(build)
    extra_context["__include_path_prefix"] = f"{rel_path}" if rel_path else ""

    extra_context["_component_name"] = cwd.name
    extra_context["_component_namespace"] = (
        cwd.parent.parent.name if cwd.parent.name == "Components" else cwd.name
    )
    code, gen_path = _instantiate_template(
        build,
        source,
        "rule-based test scaffold",
        extra_context=extra_context,
        register=False,
        overwrite_if_exists=True,  # needed to add to existing test/ut directory
        skip_if_file_exists=True,  # safety
    )
    if code != 0:
        return code
    print(
        f"[INFO] Rule-based test scaffold successfully created in {gen_path}/test/ut/ \n"
        "[INFO] For next steps, refer to the F Prime How-To Guide on Rule-Based Testing"
    )
    return 0


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
