"""fprime.fbuild.enumerator: build module enumeration strategies

This file contains the necessary enumeration strategies for build system targets. Enumeration is used to determine
what targets are available in the given contextual path (working directory). The results of the enumeration are then
passed to the target for execution.

Note: this file was created with the help of generative AI.

"""

import fnmatch
from abc import ABC, abstractmethod
from argparse import Action
from pathlib import Path
from typing import List, Tuple

from .types import MissingBuildCachePath


EnumeratedContext = Tuple[List[str], Path]
""" Context for enumeration calls (execute_all, any_supported) """


class DesignateTargetAction(Action):
    """This class, when used as the argparse action will set the target of all DesignatedBuildSystemTarget

    argparse.Action actions can be used to handle custom behavior when parsing commands. This class will use the
    --target flag to specify the build target on all known DesignatedBuildSystemTarget that have registered with this
    class.
    """

    _DESIGNEES = []

    @classmethod
    def register_designee(cls, designee):
        """Register designee to this action"""
        cls._DESIGNEES.append(designee)

    def __call__(self, parser, namespace, values, option_string=None):
        """Required __call__ function triggered by the parse"""

        # For each designee, update the build system target
        for designee in self._DESIGNEES:
            designee.set_build_targets(values)
        # The build target detection looks for true/false flags to be set. Mimic this by setting 'target' to True
        setattr(namespace, "target", True)


class ExcludeTargetAction(Action):
    """argparse action collecting --exclude patterns and handing them to every FilteredBuildTargetEnumerator

    Each occurrence of --exclude appends its pattern to the namespace list and pushes the accumulated list to all
    registered filters, mirroring how DesignateTargetAction feeds --target to the designated enumerators.
    """

    _FILTERS = []

    @classmethod
    def register_filter(cls, filter_enumerator):
        """Register a filter enumerator to receive command line patterns"""
        cls._FILTERS.append(filter_enumerator)

    def __call__(self, parser, namespace, values, option_string=None):
        """Required __call__ function triggered by the parse"""
        patterns = list(getattr(namespace, self.dest, None) or []) + list(values)
        setattr(namespace, self.dest, patterns)
        for filter_enumerator in self._FILTERS:
            filter_enumerator.set_cli_patterns(patterns)


class BuildTargetEnumerator(ABC):
    """Abstract base class for target enumeration strategies."""

    @abstractmethod
    def enumerate(self, builder: "Build", context_path: Path) -> EnumeratedContext:
        """Enumerates build targets available in the given context path."""
        raise NotImplementedError()


class FilteredBuildTargetEnumerator(BuildTargetEnumerator):
    """Wraps another enumerator and drops targets matching exclusion patterns

    Patterns are shell-style globs (fnmatch) matched against the full build target or test name, e.g. 'Svc_Foo*' or
    '*_ut_exe'. They are read from the 'excluded_targets' setting (settings.ini, whitespace separated) and from the
    --exclude command line flag; both sources are combined.
    """

    SETTING = "excluded_targets"

    def __init__(self, delegate: BuildTargetEnumerator):
        """Construct the filter around the delegate enumerator"""
        self.delegate = delegate
        self.cli_patterns = []
        ExcludeTargetAction.register_filter(self)

    def set_cli_patterns(self, patterns: List[str]):
        """Set the patterns supplied on the command line"""
        self.cli_patterns = list(patterns)

    def get_patterns(self, builder: "Build") -> List[str]:
        """Combined exclusion patterns from settings and command line"""
        setting = builder.get_settings(self.SETTING, "") or ""
        return setting.split() + self.cli_patterns

    @staticmethod
    def is_excluded(target: str, patterns: List[str]) -> bool:
        """Does the target match any of the exclusion patterns"""
        return any(fnmatch.fnmatchcase(target, pattern) for pattern in patterns)

    def enumerate(self, builder: "Build", context_path: Path) -> EnumeratedContext:
        """Enumerates with the delegate then removes excluded targets"""
        targets, path = self.delegate.enumerate(builder, context_path)
        patterns = self.get_patterns(builder)
        if not patterns:
            return targets, path
        kept = []
        for target in targets:
            if self.is_excluded(target, patterns):
                print(f"[INFO] Excluding target: {target}")
            else:
                kept.append(target)
        return kept, path


class BasicBuildTargetEnumerator(BuildTargetEnumerator):
    """A basic enumerator that just returns the context given."""

    def __init__(self, target_suffix: str = ""):
        self.target_suffix = target_suffix

    def enumerate_helper(self, builder: "Build", context_path: Path) -> List[str]:
        """Enumeration helper without error handling"""
        module = builder.cmake.get_cmake_module(context_path, builder.build_dir)
        if module and self.target_suffix:
            return [module + "_" + self.target_suffix]
        elif module:
            return [module]
        return [self.target_suffix]

    def enumerate(self, builder: "Build", context_path: Path) -> EnumeratedContext:
        """Enumerate through conversion to cmake module name directly"""
        return self.enumerate_helper(builder, context_path), context_path


class MultiBuildTargetEnumerator(BuildTargetEnumerator):
    """Enumerates targets from the 'build-targets.fprime-util' file."""

    BUILD_TARGETS_FILE = "build-targets.fprime-util"
    TEST_BUILD_TARGETS_FILE = "tests.fprime-util"

    def __init__(
        self,
        build_file_name: str = BUILD_TARGETS_FILE,
        fail_safe_enumerator: BuildTargetEnumerator = None,
    ):
        """Construct the enumerator with the name of the file"""
        self.build_file_name = build_file_name
        self.fail_safe_enumerator = (
            BasicBuildTargetEnumerator()
            if fail_safe_enumerator is None
            else fail_safe_enumerator
        )

    def enumerate_helper(self, builder: "Build", context_path: Path) -> List[str]:
        """Enumeration helper without error handling"""
        build_cache_path = builder.get_build_cache_path(context_path)
        build_targets_file = build_cache_path / self.build_file_name
        with open(build_targets_file, "r") as file_handle:
            enumerated_targets = [line.strip() for line in file_handle.readlines()]
        return enumerated_targets

    def enumerate(self, builder: "Build", context_path: Path) -> EnumeratedContext:
        """Enumerates build targets, falling back to the context if not found."""
        try:
            return self.enumerate_helper(builder, context_path), context_path
        # should an error occur, delegate to a basic enumeration strategy
        except (MissingBuildCachePath, FileNotFoundError):
            return self.fail_safe_enumerator.enumerate(builder, context_path)


class RecursiveMultiBuildTargetEnumerator(BuildTargetEnumerator):
    """Recursively enumerates targets."""

    SUBDIRECTORIES_FILE = "sub-directories.fprime-util"

    def __init__(self, directory_enumerator: "MultiBuildTargetEnumerator" = None):
        """Construct the enumerator with the name of the file"""
        self.directory_enumerator = (
            directory_enumerator
            if directory_enumerator is not None
            else MultiBuildTargetEnumerator()
        )

    def enumerate_helper(self, builder: "Build", context_path: Path) -> List[str]:
        """Enumeration helper without error handling"""
        enumerated_targets = []
        try:
            # Get local targets
            try:
                enumerated_targets.extend(
                    self.directory_enumerator.enumerate_helper(builder, context_path)
                )
            except FileNotFoundError:
                pass  # No local targets, continue to recursion

            # Recurse through subdirectories
            build_cache_path = builder.get_build_cache_path(context_path)
            sub_directories_file = build_cache_path / self.SUBDIRECTORIES_FILE
            with open(sub_directories_file, "r") as file_handle:
                for sub_dir in file_handle.readlines():
                    # Each line is a new path relative to the current context
                    # We need to construct the full path for the recursive call
                    full_sub_dir_path = (build_cache_path / sub_dir.strip()).resolve()
                    enumerated_targets.extend(
                        self.enumerate_helper(builder, full_sub_dir_path)
                    )
        # Any error should return the result of the last update to enumerate_targets hance passing
        except (MissingBuildCachePath, FileNotFoundError):
            pass
        return enumerated_targets

    def enumerate(self, builder: "Build", context_path: Path) -> EnumeratedContext:
        """Recursively enumerates build targets."""
        enumerated_targets = self.enumerate_helper(builder, context_path)
        enumerated_targets = (
            enumerated_targets
            if enumerated_targets
            else self.directory_enumerator.enumerate(builder, context_path)[0]
        )
        return enumerated_targets, context_path


class SpecificBuildTargetEnumerator(BuildTargetEnumerator):
    """Enumerates a specific singular build target"""

    def __init__(self, build_targets: List[str] = None):
        """Construct the enumerator with the name of the build target"""
        self.build_targets = build_targets if build_targets is not None else []

    def set_build_targets(self, build_targets: List[str]):
        """Set the build targets"""
        self.build_targets = build_targets

    def enumerate(self, builder: "Build", context_path: Path) -> EnumeratedContext:
        """Enumerates exactly a build target"""
        return self.build_targets, builder.cmake_root


class CliBuildTargetEnumerator(SpecificBuildTargetEnumerator):
    """Allows users to specify a build target on the command line"""

    def __init__(self):
        super().__init__(build_targets=None)
        DesignateTargetAction.register_designee(self)
