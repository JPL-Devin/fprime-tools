"""
Import-compatibility safety net for external consumers of fprime-tools.

External projects (nasa/fprime tooling, cookiecutter template hooks, user
scripts) import these module paths and symbols. Every path here must remain
importable, and every symbol must remain present, across refactors. When a
module moves, keep the old path as a shim and extend this test with an
old-path/new-path module identity assertion.
"""

import importlib

import pytest

# (module path, symbols known to be used by external consumers)
PUBLIC_SYMBOLS = [
    ("fprime.fbuild.builder", ["Build", "BuildType", "GenerateException"]),
    ("fprime.fbuild.settings", ["IniSettings"]),
    ("fprime.fbuild.types", ["BuildType"]),
    ("fprime.fbuild.cmake", ["CMakeHandler", "CMakeExecutionException"]),
    ("fprime.fbuild.target", ["Target", "TargetScope"]),
    ("fprime.fbuild.target_definitions", []),
    ("fprime.fbuild.check", ["CheckTarget"]),
    ("fprime.fbuild.gcovr", ["Gcovr", "GcovrTarget"]),
    ("fprime.fbuild.enumerator", ["BuildTargetEnumerator"]),
    ("fprime.fbuild.cli", ["add_fbuild_parsers"]),
    ("fprime.util.cli", ["utility_entry", "parse_args"]),
    ("fprime.util.commands", ["run_info", "run_new"]),
    ("fprime.util.build_helper", ["load_build"]),
    ("fprime.util.help_text", ["HelpText"]),
    ("fprime.util.versioning", ["get_version", "VersionException"]),
    ("fprime.util.code_formatter", ["ClangFormatter"]),
    ("fprime.util.cookiecutter_wrapper", ["is_valid_name", "new_component"]),
    ("fprime.util.file_util", ["get_directory_path_relative_to_root"]),
    ("fprime.fpp.cli", ["add_fpp_parsers"]),
    ("fprime.fpp.common", ["FppUtility"]),
    ("fprime.fpp.impl", ["fpp_generate_implementation"]),
    ("fprime.fpp.visualize", ["add_fpp_viz_parsers"]),
    ("fprime.common.utils", ["confirm", "replace_contents"]),
    ("fprime.common.error", ["FprimeException"]),
]

# Serialize modules are shims that re-export from fprime-gds when installed, and
# raise a documented ImportError pointing at fprime-gds when it is not.
SERIALIZE_SHIMS = [
    ("fprime.common.models.serialize.numerical_types", ["U32Type", "I8Type"]),
    ("fprime.common.models.serialize.string_type", ["StringType"]),
    ("fprime.common.models.serialize.enum_type", ["EnumType"]),
    ("fprime.common.models.serialize.serializable_type", ["SerializableType"]),
    ("fprime.common.models.serialize.array_type", ["ArrayType"]),
    ("fprime.common.models.serialize.bool_type", ["BoolType"]),
    ("fprime.common.models.serialize.time_type", ["TimeType"]),
    ("fprime.common.models.serialize.type_base", ["BaseType"]),
    ("fprime.common.models.serialize.type_exceptions", ["TypeException"]),
]


@pytest.mark.parametrize(
    "module_path,symbols", PUBLIC_SYMBOLS, ids=[m for m, _ in PUBLIC_SYMBOLS]
)
def test_public_import_paths(module_path, symbols):
    """Tests that public module paths import and expose their known-used symbols"""
    module = importlib.import_module(module_path)
    for symbol in symbols:
        assert hasattr(module, symbol), f"{module_path} lost symbol {symbol}"


# Old (deprecated) module path -> new module path. Old paths are kept as
# sys.modules aliases so both names refer to the exact same module object.
MOVED_MODULES = {
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


@pytest.mark.parametrize(
    "old_path,new_path", MOVED_MODULES.items(), ids=list(MOVED_MODULES)
)
def test_moved_module_identity(old_path, new_path):
    """Tests that old module paths alias the exact same module object as the new paths"""
    old_module = importlib.import_module(old_path)
    new_module = importlib.import_module(new_path)
    assert old_module is new_module, f"{old_path} is not an alias of {new_path}"


@pytest.mark.parametrize(
    "module_path,symbols", SERIALIZE_SHIMS, ids=[m for m, _ in SERIALIZE_SHIMS]
)
def test_serialize_shim_import_paths(module_path, symbols):
    """Tests that serialize shims re-export from fprime-gds or raise the documented error"""
    try:
        module = importlib.import_module(module_path)
    except ImportError as error:
        assert "fprime-gds" in str(error), f"{module_path} lost its fprime-gds pointer"
        return
    for symbol in symbols:
        assert hasattr(module, symbol), f"{module_path} lost symbol {symbol}"
