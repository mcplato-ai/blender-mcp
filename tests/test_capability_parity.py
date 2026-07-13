from __future__ import annotations

import argparse
import ast
import unittest
from pathlib import Path

from blender_mcp.cli import COMMAND_SCHEMA, build_parser


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon.py"
LEGACY_CLIENT_PATHS = (
    PROJECT_ROOT / "src" / "blender_mcp" / "server.py",
    PROJECT_ROOT / "src" / "blender_mcp" / "telemetry.py",
)
CLI_ONLY_COMMAND_TYPES = {
    "raw_call",
    "schema",
    "skill_install",
    "skill_path",
    "status_all",
}
SCHEMA_RAW_COMMAND_TYPE = "ANY_ADDON_COMMAND"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _addon_command_types() -> set[str]:
    tree = _parse(ADDON_PATH)
    dispatch_functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_execute_command_internal"
    ]
    if len(dispatch_functions) != 1:
        raise AssertionError(
            "Expected exactly one Blender add-on _execute_command_internal method"
        )

    command_types: set[str] = set()
    for node in ast.walk(dispatch_functions[0]):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            is_handler_table = any(
                isinstance(target, ast.Name)
                and (target.id == "handlers" or target.id.endswith("_handlers"))
                for target in node.targets
            )
            if is_handler_table:
                command_types.update(
                    key.value
                    for key in node.value.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                )

        # Include commands handled by a direct branch before the handler tables.
        if (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == "cmd_type"
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.Eq)
            and len(node.comparators) == 1
            and isinstance(node.comparators[0], ast.Constant)
            and isinstance(node.comparators[0].value, str)
        ):
            command_types.add(node.comparators[0].value)

    if not command_types:
        raise AssertionError("No Blender add-on command handlers were found")
    return command_types


def _legacy_send_command_types() -> set[str]:
    command_types: set[str] = set()
    dynamic_calls: list[str] = []

    for path in LEGACY_CLIENT_PATHS:
        for node in ast.walk(_parse(path)):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "send_command"
            ):
                continue
            if (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                command_types.add(node.args[0].value)
            else:
                dynamic_calls.append(f"{path.name}:{node.lineno}")

    if dynamic_calls:
        raise AssertionError(
            "Capability parity cannot verify dynamic send_command calls at "
            + ", ".join(dynamic_calls)
        )
    if not command_types:
        raise AssertionError("No legacy send_command calls were found")
    return command_types


def _parser_command_types() -> set[str]:
    command_types: set[str] = set()

    def visit(parser: argparse.ArgumentParser) -> None:
        command_type = parser._defaults.get("command_type")
        if isinstance(command_type, str):
            command_types.add(command_type)
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for child in action.choices.values():
                    visit(child)

    visit(build_parser())
    return command_types


def _schema_command_types() -> tuple[set[str], list[dict]]:
    entries = COMMAND_SCHEMA["commands"]
    raw_entries = [
        entry for entry in entries if entry["type"] == SCHEMA_RAW_COMMAND_TYPE
    ]
    wire_types = {
        entry["type"]
        for entry in entries
        if entry["type"] != SCHEMA_RAW_COMMAND_TYPE
    }
    return wire_types, raw_entries


class CapabilityParityTests(unittest.TestCase):
    def test_legacy_mcp_client_covers_every_addon_command(self):
        self.assertSetEqual(_legacy_send_command_types(), _addon_command_types())

    def test_cli_parser_covers_every_addon_command(self):
        addon_types = _addon_command_types()
        parser_types = _parser_command_types()

        self.assertSetEqual(parser_types - addon_types, CLI_ONLY_COMMAND_TYPES)
        self.assertSetEqual(parser_types - CLI_ONLY_COMMAND_TYPES, addon_types)

    def test_cli_schema_covers_every_addon_command(self):
        schema_types, raw_entries = _schema_command_types()

        self.assertSetEqual(schema_types, _addon_command_types())
        self.assertEqual(len(raw_entries), 1)
        self.assertEqual(raw_entries[0]["cli"], "raw call TYPE")


if __name__ == "__main__":
    unittest.main()
