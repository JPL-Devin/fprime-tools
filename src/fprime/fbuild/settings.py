"""
fprime.fbuild.settings:

An implementation used to pull settings into the fprime build. This version uses INI files in order
to load the settings from the settings.default file that is part of the F prime project directory.

@author mstarch
"""

import configparser
import os
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Union


class EnvironmentVariableInterpolation(configparser.BasicInterpolation):
    """Interpolation for environment variables embedded in setting.ini

    settings.ini will extrapolate $/${} as an environment variable. This will allow basic environment variable
    replacement. It is illegal to supply an environment variable with a $ or %( as part of the value because that might
    trigger unanticipated recursive parsing.

    Note: environment variable substitution is only performed in the environment section and nowhere else.

    Based off: https://stackoverflow.com/questions/26586801/configparser-and-string-interpolation-with-env-variable
    """

    def before_get(self, parser, section, option, value, defaults):
        """Pre-process sections to replace environment variables

        Runs before the value is gotten to replace environment variables. It will use os.path.expandvars to do the
        actual substitution on any value in the "environment" section. Other pre-processing is done first.

        Args:
            parser: unused
            section: environment substitution will be done only when set to "environment"
            option: unused
            value: will be searched for and replace environment variables
            defaults: unused
        Returns:
            the value post substitution
        """
        value = super().before_get(parser, section, option, value, defaults)
        return os.path.expandvars(value) if section == "environment" else value


class SettingType(Enum):
    """Designates the type of the setting"""

    PATH = 0
    PATH_LIST = 1
    STRING = 2



class IniSettings:
    """Class to load settings from INI files"""

    DEF_FILE = "settings.ini"
    SET_ENV = "FPRIME_SETTINGS_FILE"

    FPRIME_FIELDS = [
        ("framework_path", SettingType.PATH, None),
        ("project_root", SettingType.PATH, None),
        ("default_toolchain", SettingType.STRING, None),
        ("default_ut_toolchain", SettingType.STRING, None),
        ("library_locations", SettingType.PATH_LIST, None),
        ("component_cookiecutter", SettingType.STRING, None),
        ("deployment_cookiecutter", SettingType.STRING, None),
    ]

    PLATFORM_FIELDS = [
        ("config_directory", SettingType.PATH, None),
        ("install_destination", SettingType.PATH, None),
        ("environment_file", SettingType.PATH, None),
        ("default_cmake_options", SettingType.STRING, None),
    ]

    @staticmethod
    def read_safe_path(
        parser: configparser.ConfigParser,
        section: str,
        key: str,
        ini_file: Path,
        exists: bool = True,
    ) -> List[Path]:
        """
        Reads path(s), safely, from the config parser.  Validates the path(s) exists or raises an exception. Paths are
        separated by ':'.  This will also expand relative paths relative to the settings file.

        :param parser: parser to read from
        :param section: section to read from
        :param key: key to read from
        :param ini_file: ini_file path for clean errors
        :param exists: expect the path to exist. Default: True, must exist.
        :return: path, validated
        """
        base_dir = os.path.dirname(ini_file)
        all_paths = parser.get(section, key, fallback="").split(":")
        expanded = []
        for path in all_paths:
            if not path:
                continue
            full_path = os.path.abspath(os.path.normpath(os.path.join(base_dir, path)))
            if exists and not os.path.exists(full_path):
                msg = f"Nonexistent path '{path}' found in section '{section}' option '{key}' of file '{ini_file}'"
                raise FprimeSettingsException(msg)
            expanded.append(Path(full_path).resolve())
        return expanded

    @staticmethod
    def read_setting(
        config_parser: configparser.ConfigParser,
        settings: Dict[str, Any],
        section: str,
        key: str,
        settings_type: SettingType,
        default: Union[Callable, Any],
    ):
        """Reads an individual setting"""

        def get_default_value():
            """Calculates the default value for the given setting"""
            return default(settings) if callable(default) else default

        if config_parser is None:
            value = get_default_value()
        elif settings_type == SettingType.STRING:
            value = config_parser.get(section, key, fallback=get_default_value())
        elif settings_type == SettingType.PATH:
            paths_list = IniSettings.read_safe_path(
                config_parser,
                section,
                key,
                settings["settings_file"],
                key != "install_destination",
            )
            value = paths_list[0] if paths_list else get_default_value()
        elif settings_type == SettingType.PATH_LIST:
            paths_list = IniSettings.read_safe_path(
                config_parser,
                section,
                key,
                settings["settings_file"],
                key != "install_destination",
            )
            value = paths_list or get_default_value()
        else:
            raise FprimeSettingsException("Invalid settings specification")
        return value

    @staticmethod
    def load(settings_file: Path, platform: str = "native", is_ut: bool = False):
        """
        Load settings from specified file or from specified build directory. Either a specific file or the build
        directory must be not None.

        :param settings_file: file to load settings from (in INI format). Must be specified if build_dir is not.
        :param platform: platform to read platform specific settings
        :param is_ut: is this a unit test build
        :return: a dictionary of needed settings
        """
        settings_file = (
            Path.cwd() / IniSettings.DEF_FILE
            if settings_file is None
            else settings_file
        ).resolve()
        # Setup a config parser, or none if the settings file does not exist
        confparse = None
        if settings_file.exists():
            confparse = configparser.ConfigParser(
                interpolation=EnvironmentVariableInterpolation()
            )
            confparse.read(settings_file)
        else:
            print(f"[WARNING] {settings_file} does not exist", file=sys.stderr)

        settings = {
            "_cmake_project_root": settings_file.parent,
        }
        if settings_file.exists():
            settings["settings_file"] = settings_file

        # Read fprime and platform settings from the "fprime" section
        for key, settings_type, default in (
            IniSettings.FPRIME_FIELDS + IniSettings.PLATFORM_FIELDS
        ):
            value = IniSettings.read_setting(
                confparse, settings, "fprime", key, settings_type, default
            )
            if value is not None:
                settings[key] = value

        # Calculate the platform if not specified
        if not platform or platform == "default":
            platform = (
                settings.get("default_ut_toolchain", "native")
                if is_ut
                else settings.get("default_toolchain", "native")
            )

        # Read platform settings overtop of fprime settings
        for key, settings_type, default in IniSettings.PLATFORM_FIELDS:
            value = IniSettings.read_setting(
                confparse,
                settings,
                platform,
                key,
                settings_type,
                settings.get(key, default),
            )
            if value is not None:
                settings[key] = value

        env_file = settings.get("environment_file") or settings.get("settings_file")
        if env_file is not None:
            settings["environment"] = IniSettings.load_environment(env_file)
        else:
            settings["environment"] = {}
        del settings["_cmake_project_root"]

        # add _fprime_packages to library locations
        project_root = settings.get("project_root")
        if project_root is not None:
            try:
                packages_dir = project_root / "_fprime_packages"
                if os.path.exists(packages_dir):
                    if settings.get("library_locations") is None:
                        settings["library_locations"] = []
                    for folder in os.listdir(packages_dir):
                        settings["library_locations"].append(
                            Path(packages_dir / folder)
                        )
            except FileNotFoundError:
                pass

        return settings

    @staticmethod
    def load_environment(env_file):
        """
        Load the environment from the given parser.

        :param env_file: load environment from this file
        :return: environment dictionary
        """
        parser = configparser.ConfigParser(
            interpolation=EnvironmentVariableInterpolation()
        )
        parser.optionxform = str
        parser.read(env_file)
        env_dict = {}
        try:
            for key, value in parser.items("environment"):
                env_dict[key] = value
        except configparser.NoSectionError:
            pass  # Ignore missing environment
        return env_dict


class FprimeLocationUnknownException(Exception):
    """Fprime location could not be determined"""


class FprimeSettingsException(Exception):
    """An exception for handling F prime settings misconfiguration"""
