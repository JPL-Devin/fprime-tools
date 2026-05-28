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
                "framework_path": full_path(".."),
                "environment": {},
            },
        },
        {
            "file": "settings-custom-install.ini",
            "expected": {
                "settings_file": full_path("settings-data/settings-custom-install.ini"),
                "framework_path": full_path(".."),
                "install_destination": full_path("test"),
                "environment": {},
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
                "environment": {},
            },
        },
        {
            "file": "settings-outside-cookiecutter.ini",
            "expected": {
                "settings_file": full_path(
                    "settings-data/settings-outside-cookiecutter.ini"
                ),
                "framework_path": full_path(".."),
                "component_cookiecutter": "gh:SterlingPeet/cookiecutter-fprime-deployment",
                "deployment_cookiecutter": "https://github.com/thomas-bc/fprime-deployment-cookiecutter.git",
                "environment": {},
            },
        },
        {
            "file": "settings-multi-line-default-options.ini",
            "expected": {
                "settings_file": full_path(
                    "settings-data/settings-multi-line-default-options.ini"
                ),
                "framework_path": full_path(".."),
                "default_cmake_options": "OPTION1=ABC\nOPTION2=123\nOPTION3=Something",
                "environment": {},
            },
        },
        {
            "file": "settings-environment.ini",
            "expected": {
                "settings_file": full_path("settings-data/settings-environment.ini"),
                "framework_path": full_path(".."),
                "environment": {},
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
