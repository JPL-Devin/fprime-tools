"""
(test) fprime.fbuild.settings:

Tests the F prime settings module.
@author joshuaa
"""

import os
from pathlib import Path

from fprime.fbuild.settings import IniSettings

LOCAL_PATH = Path(__file__).parent


def full_path(path):
    path = LOCAL_PATH / Path(path)
    return path.resolve()


# The following tests use a fake framework path due to the separation of fprime and fprime-tools


def test_settings():
    test_cases = [
        {
            "file": "settings-empty.ini",
            "expected": {
                "settings_file": full_path("settings-data/settings-empty.ini"),
                "default_toolchain": None,
                "default_ut_toolchain": None,
                "framework_path": full_path(".."),
                "install_destination": None,
                "library_locations": None,
                "environment_file": None,
                "environment": {},
                "component_cookiecutter": None,
                "deployment_cookiecutter": None,
                "project_root": None,
                "config_directory": None,
                "default_cmake_options": None,
            },
        },
        {
            "file": "settings-custom-install.ini",
            "expected": {
                "settings_file": full_path("settings-data/settings-custom-install.ini"),
                "default_toolchain": None,
                "default_ut_toolchain": None,
                "framework_path": full_path(".."),
                "install_destination": full_path("test"),
                "library_locations": None,
                "environment_file": None,
                "environment": {},
                "component_cookiecutter": None,
                "deployment_cookiecutter": None,
                "project_root": None,
                "config_directory": None,
                "default_cmake_options": None,
            },
        },
        {
            "file": "settings-custom-toolchain.ini",
            "expected": {
                "settings_file": full_path(
                    "settings-data/settings-custom-toolchain.ini"
                ),
                "default_toolchain": "custom1",
                "default_ut_toolchain": "custom2",
                "framework_path": full_path(".."),
                "install_destination": None,
                "library_locations": None,
                "environment_file": None,
                "environment": {},
                "component_cookiecutter": None,
                "deployment_cookiecutter": None,
                "project_root": None,
                "config_directory": None,
                "default_cmake_options": None,
            },
        },
        {
            "file": "settings-outside-cookiecutter.ini",
            "expected": {
                "settings_file": full_path(
                    "settings-data/settings-outside-cookiecutter.ini"
                ),
                "default_toolchain": None,
                "default_ut_toolchain": None,
                "framework_path": full_path(".."),
                "install_destination": None,
                "library_locations": None,
                "environment_file": None,
                "environment": {},
                "component_cookiecutter": "gh:SterlingPeet/cookiecutter-fprime-deployment",
                "deployment_cookiecutter": "https://github.com/thomas-bc/fprime-deployment-cookiecutter.git",
                "project_root": None,
                "config_directory": None,
                "default_cmake_options": None,
            },
        },
        {
            "file": "settings-multi-line-default-options.ini",
            "expected": {
                "settings_file": full_path(
                    "settings-data/settings-multi-line-default-options.ini"
                ),
                "default_toolchain": None,
                "default_ut_toolchain": None,
                "framework_path": full_path(".."),
                "install_destination": None,
                "library_locations": None,
                "environment_file": None,
                "environment": {},
                "component_cookiecutter": None,
                "deployment_cookiecutter": None,
                "project_root": None,
                "config_directory": None,
                "default_cmake_options": "OPTION1=ABC\nOPTION2=123\nOPTION3=Something",
            },
        },
        {
            "file": "settings-environment.ini",
            "expected": {
                "settings_file": full_path("settings-data/settings-environment.ini"),
                "default_toolchain": None,
                "default_ut_toolchain": None,
                "framework_path": full_path(".."),
                "install_destination": None,
                "library_locations": None,
                "environment_file": None,
                "environment": {},
                "component_cookiecutter": None,
                "deployment_cookiecutter": None,
                "project_root": None,
                "config_directory": None,
                "default_cmake_options": None,
            },
        },
    ]
    # Prep for substitution
    os.environ["TEST_SETTING_1"] = "abc"
    os.environ["TEST_SETTING_2"] = "123"
    for case in test_cases:
        fp = full_path("settings-data/" + case["file"])
        results = IniSettings.load(fp)
        assert (
            case["expected"] == results
        ), f'{fp}: Expected {case["expected"]}, got {results}'
