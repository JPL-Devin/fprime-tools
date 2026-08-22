import os
import subprocess

from fprime.common.error import FprimeException


class FppInvocationException(FprimeException):
    """An fpp tool invocation failed"""


def _run_fpp(arguments, env=None) -> str:
    """Run an fpp tool, returning its stdout or raising FppInvocationException"""
    try:
        completed = subprocess.run(
            arguments,
            check=True,
            stdout=subprocess.PIPE,
            env=env,
        )
        return completed.stdout.decode("utf-8")
    except subprocess.CalledProcessError as error:
        raise FppInvocationException(
            f"{arguments[0]} failed with error: {error}"
        ) from error


def fpp_depend(cache_folder, input_file, locs_files, env=None) -> str:
    """
    This function calculates the dependencies for an fpp file using fprime-util to get
    the location of the build cache fpp-depend.

    Args:
        cache_folder: folder to write the dependency output files into
        input_file: The input fpp file to calculate dependencies for
        locs_files: The locs.fpp files to use for dependency calculation
        env: optional environment for the fpp-depend subprocess

    Returns:
        A string of dependencies for the input file
    """

    print(f"[fpp] Calculating fpp dependencies for {os.path.basename(input_file)}...")

    stdout = _run_fpp(
        ["fpp-depend", input_file]
        + locs_files
        + [
            "-d",
            f"{cache_folder}/direct.txt",
            "-m",
            f"{cache_folder}/missing.txt",
            "-f",
            f"{cache_folder}/framework.txt",
            "-g",
            f"{cache_folder}/generated.txt",
            "-i",
            f"{cache_folder}/include.txt",
            "-u",
            f"{cache_folder}/unittest.txt",
            "-a",
        ],
        env=env,
    )

    with open(f"{cache_folder}/stdout.txt", "w") as f:
        f.write(stdout)

    return stdout


def compute_simple_dependencies(locs_file, input, env=None) -> str:
    """Run fpp-depend with just a locs file, returning its stdout"""
    print(f"[fpp] Calculating simple fpp dependencies for {os.path.basename(input)}...")

    return _run_fpp(["fpp-depend", locs_file, input], env=env)


def fpp_to_json(input_file, env=None):
    """
    This function runs fpp-to-json on an fpp file to generate a JSON AST.

    Args:
        input_file: The input fpp file to run fpp-to-json on
        env: optional environment for the fpp-to-json subprocess

    Returns:
        None
    """

    # run fpp
    print(f"[fpp] Running fpp-to-json for {os.path.basename(input_file)}...")

    _run_fpp(["fpp-to-json", input_file, "-s"], env=env)


def fpp_format(input_file, env=None) -> str:
    """
    This function runs fpp-format on an fpp file to format the file.

    Args:
        input_file: The input fpp file to run fpp-format on
        env: optional environment for the fpp-format subprocess

    Returns:
        The formatted file contents
    """

    # run fpp-format
    print(f"[fpp] Running fpp-format for {os.path.basename(input_file)}...")

    return _run_fpp(["fpp-format", input_file], env=env)


def fpp_locate_defs(input_file, env=None) -> str:
    """
    This function runs fpp-locate-defs on an fpp file to locate definitions.

    Args:
        input_file: The input fpp file to run fpp-locate-defs on
        env: optional environment for the fpp-locate-defs subprocess

    Returns:
        The located definitions output
    """

    print(f"[fpp] Running fpp-locate-defs for {os.path.basename(input_file)}...")

    base_dir = os.path.dirname(input_file)

    return _run_fpp(["fpp-locate-defs", input_file, "-d", base_dir], env=env)
