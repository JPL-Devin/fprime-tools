"""
Import-compatibility safety net ahead of the WP8 module reorganization.

Asserts that every public module path importable today stays importable, and that
the specific symbols known consumers use remain available at their current paths.
Module-identity assertions (old path is new path) are added in WP8.
"""

import importlib
import importlib.util

import pytest

PUBLIC_MODULE_PATHS = [
    "fprime.fbuild.builder",
    "fprime.fbuild.cmake",
    "fprime.fbuild.settings",
    "fprime.fbuild.types",
    "fprime.fbuild.target",
    "fprime.fbuild.target_definitions",
    "fprime.fbuild.check",
    "fprime.fbuild.gcovr",
    "fprime.fbuild.enumerator",
    "fprime.fbuild.cli",
    "fprime.util.cli",
    "fprime.util.commands",
    "fprime.util.build_helper",
    "fprime.util.help_text",
    "fprime.util.versioning",
    "fprime.util.code_formatter",
    "fprime.util.cookiecutter_wrapper",
    "fprime.util.file_util",
    "fprime.fpp.common",
    "fprime.fpp.impl",
    "fprime.fpp.merge",
    "fprime.fpp.visualize",
    "fprime.fpp.cli",
    "fprime.fpp.utils.fpp_to_json.fpp_interface",
    "fprime.fpp.utils.fpp_to_json.helpers",
    "fprime.fpp.utils.fpp_to_json.node_structs",
    "fprime.fpp.utils.fpp_to_json.visitors",
    "fprime.common.error",
    "fprime.common.utils",
    "fprime.common.models.serialize.array_type",
    "fprime.common.models.serialize.bool_type",
    "fprime.common.models.serialize.enum_type",
    "fprime.common.models.serialize.numerical_types",
    "fprime.common.models.serialize.serializable_type",
    "fprime.common.models.serialize.string_type",
    "fprime.common.models.serialize.time_type",
    "fprime.common.models.serialize.type_base",
    "fprime.common.models.serialize.type_exceptions",
]

OLD_TO_NEW_MODULE_PATHS = {
    "fprime.fbuild.builder": "fprime.build.builder",
    "fprime.fbuild.cmake": "fprime.build.cmake",
    "fprime.fbuild.settings": "fprime.build.settings",
    "fprime.fbuild.types": "fprime.build.types",
    "fprime.fbuild.target": "fprime.build.targets.target",
    "fprime.fbuild.target_definitions": "fprime.build.targets",
    "fprime.fbuild.check": "fprime.build.targets.check",
    "fprime.fbuild.gcovr": "fprime.build.targets.gcovr",
    "fprime.fbuild.enumerator": "fprime.build.targets.enumerator",
    "fprime.fbuild.cli": "fprime.cli.fbuild",
    "fprime.util.cli": "fprime.cli.entry",
    "fprime.util.commands": "fprime.cli.commands",
    "fprime.util.build_helper": "fprime.cli.build_helper",
    "fprime.util.help_text": "fprime.cli.help_text",
    "fprime.util.versioning": "fprime.cli.versioning",
    "fprime.util.code_formatter": "fprime.tools.clang_format",
    "fprime.util.cookiecutter_wrapper": "fprime.tools.cookiecutter",
    "fprime.fpp.common": "fprime.tools.fpp.common",
    "fprime.fpp.impl": "fprime.tools.fpp.impl",
    "fprime.fpp.merge": "fprime.tools.fpp.merge",
    "fprime.fpp.visualize": "fprime.tools.fpp.visualize",
    "fprime.fpp.cli": "fprime.cli.fpp",
}

CONSUMED_SYMBOLS = {
    "fprime.fbuild.settings": ["IniSettings"],
    "fprime.fbuild.builder": ["Build", "BuildType", "Target"],
    "fprime.fbuild.types": ["BuildType"],
    "fprime.fbuild.target": ["Target"],
    "fprime.fbuild.cmake": ["CMakeHandler", "CMakeExecutionException"],
    "fprime.util.cli": ["utility_entry"],
    "fprime.util.cookiecutter_wrapper": ["is_valid_name"],
    "fprime.fpp.common": ["FppUtility"],
    "fprime.common.models.serialize.numerical_types": [
        "I8Type",
        "I16Type",
        "I32Type",
        "I64Type",
        "U8Type",
        "U16Type",
        "U32Type",
        "U64Type",
        "F32Type",
        "F64Type",
    ],
}


@pytest.mark.parametrize("module_path", PUBLIC_MODULE_PATHS)
def test_public_module_importable(module_path):
    """Every public module path remains importable"""
    if module_path.startswith(
        "fprime.common.models.serialize."
    ) and not importlib.util.find_spec("fprime_gds"):
        pytest.skip("serialize shims re-export from fprime_gds, which is not installed")
    module = importlib.import_module(module_path)
    for symbol in CONSUMED_SYMBOLS.get(module_path, []):
        assert hasattr(module, symbol), f"{module_path} no longer exposes {symbol}"


@pytest.mark.parametrize("old_path,new_path", OLD_TO_NEW_MODULE_PATHS.items())
def test_old_and_new_paths_are_same_module(old_path, new_path):
    """Every relocated module is the same object at its old and new path"""
    old_module = importlib.import_module(old_path)
    new_module = importlib.import_module(new_path)
    assert old_module is new_module, f"{old_path} is not {new_path}"
