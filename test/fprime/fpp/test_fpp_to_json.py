"""Tests for the fpp_to_json utility subpackage"""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import fprime.fpp.utils.fpp_to_json.node_structs as NodeStructs
import fprime.fpp.utils.fpp_to_json.visitors.json_conversion as JSONConverter
from fprime.fpp.utils.fpp_to_json.fpp_interface import (
    FppInvocationException,
    compute_simple_dependencies,
    fpp_depend,
)
from fprime.fpp.utils.fpp_to_json.example_visitors.visit import (
    walkModule,
    walkTopology,
)

FIXTURE = (
    Path(__file__).parents[3]
    / "src"
    / "fprime"
    / "fpp"
    / "utils"
    / "fpp_to_json"
    / "example_visitors"
    / "example.fpp.ast.json"
)


def load_ast():
    with open(FIXTURE) as file_handle:
        return json.load(file_handle)


def test_walk_example_ast():
    """Walk the checked-in example AST through the converters without error"""
    ast = load_ast()
    qualified_names = []
    for member in ast[0]["members"]:
        if "DefModule" in member[1]:
            qualified_names.append(walkModule(member, ""))
        if "DefTopology" in member[1]:
            qualified_names.append(walkTopology(member, ""))
    assert qualified_names, "Example AST produced no modules or topologies"


def test_component_instance_conversion():
    """Component instances in the example AST convert with parsed fields"""
    ast = load_ast()

    def find_instances(members):
        for member in members:
            if "DefComponentInstance" in member[1]:
                yield member
            if "DefModule" in member[1]:
                yield from find_instances(
                    member[1]["DefModule"]["node"]["AstNode"]["data"]["members"]
                )

    instances = list(find_instances(ast[0]["members"]))
    assert instances, "Example AST contains no component instances"
    for member in instances:
        struct = JSONConverter.CompInstanceConverter(
            NodeStructs.ComponentInst(member)
        ).convert()
        assert struct.name
        assert struct.component_name
        assert struct.base_id is not None


def test_port_converter():
    """PortConverter parses the port name and parameters"""
    param = {
        "AstNode": {
            "data": {
                "name": "value",
                "typeName": {
                    "AstNode": {"data": {"Unqualified": {"name": "U32"}}, "id": 1}
                },
            },
            "id": 2,
        }
    }
    port_ast = [
        None,
        {
            "DefPort": {
                "node": {
                    "AstNode": {
                        "data": {
                            "name": "ExamplePort",
                            "params": [[None, param, None]],
                        },
                        "id": 3,
                    }
                }
            }
        },
        None,
    ]
    struct = JSONConverter.PortConverter(NodeStructs.Port(port_ast)).convert()
    assert struct.name == "ExamplePort"
    assert struct.qf == "ExamplePort"
    assert struct.parameters == [{"name": "value", "type": "U32"}]


def test_fpp_depend_returns_output(tmp_path):
    """fpp_depend returns fpp-depend's stdout and writes it to the cache folder"""
    completed = subprocess.CompletedProcess(
        args=["fpp-depend"], returncode=0, stdout=b"dependency.fpp\n"
    )
    with patch("subprocess.run", return_value=completed):
        output = fpp_depend(str(tmp_path), "input.fpp", ["locs.fpp"])
    assert output == "dependency.fpp\n"
    assert (tmp_path / "stdout.txt").read_text() == "dependency.fpp\n"


def test_fpp_depend_raises_typed_exception(tmp_path):
    """fpp tool failures raise FppInvocationException"""
    error = subprocess.CalledProcessError(1, ["fpp-depend"])
    with patch("subprocess.run", side_effect=error):
        with pytest.raises(FppInvocationException):
            fpp_depend(str(tmp_path), "input.fpp", ["locs.fpp"])
        with pytest.raises(FppInvocationException):
            compute_simple_dependencies("locs.fpp", "input.fpp")
