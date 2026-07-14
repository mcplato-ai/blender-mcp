from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from blender_mcp import cli as cli_module
from blender_mcp.cli import build_parser, main

from tests.fake_blender import FakeBlenderServer


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cli(arguments: list[str]):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(arguments)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class BlenderCLITests(unittest.TestCase):
    def test_top_level_help_lists_all_command_groups(self):
        parser = build_parser()
        help_text = parser.format_help()
        self.assertEqual(parser.prog, "blender-mcp-cli")
        for command in (
            "schema",
            "skill",
            "status",
            "scene",
            "object",
            "viewport",
            "code",
            "polyhaven",
            "sketchfab",
            "hyper3d",
            "hunyuan3d",
            "raw",
        ):
            self.assertIn(command, help_text)
        self.assertIn("does not use MCP", help_text)

    def test_schema_is_local_and_machine_readable(self):
        exit_code, stdout, stderr = run_cli(["schema"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(len(payload["result"]["commands"]), 24)
        self.assertIn("not HTTP", payload["result"]["transport"]["notes"][0])

    def test_skill_path_is_local_and_lists_published_files(self):
        exit_code, stdout, stderr = run_cli(["skill", "path"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        result = json.loads(stdout)["result"]
        skill_path = Path(result["path"])
        self.assertEqual(
            result["files"], ["SKILL.md", "LICENSE", "agents/openai.yaml"]
        )
        self.assertEqual(
            result["install_files"],
            ["SKILL.md", "LICENSE", "addon.py", "agents/openai.yaml"],
        )
        self.assertTrue((skill_path / "SKILL.md").is_file())
        self.assertTrue((skill_path / "LICENSE").is_file())
        self.assertTrue((skill_path / "agents/openai.yaml").is_file())
        self.assertEqual(Path(result["addon_path"]), (PROJECT_ROOT / "addon.py"))
        self.assertEqual(
            Path(result["addon_path"]).read_bytes(),
            (PROJECT_ROOT / "addon.py").read_bytes(),
        )

    def test_skill_install_help_documents_destination_and_overwrite(self):
        parser = build_parser()
        skill_action = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        skill_parser = skill_action.choices["skill"]
        install_action = next(
            action
            for action in skill_parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        help_text = install_action.choices["install"].format_help()

        self.assertIn("CODEX_HOME", help_text)
        self.assertIn("addon.py", help_text)
        self.assertIn("--target", help_text)
        self.assertIn("--force", help_text)

    def test_skill_install_requires_force_and_preserves_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "installed-skill"
            exit_code, stdout, stderr = run_cli(
                ["skill", "install", "--target", str(target)]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(
                json.loads(stdout)["result"]["target"], str(target.resolve())
            )
            self.assertTrue((target / "SKILL.md").is_file())
            self.assertTrue((target / "LICENSE").is_file())
            self.assertTrue((target / "addon.py").is_file())
            self.assertTrue((target / "agents/openai.yaml").is_file())
            self.assertEqual(
                (target / "addon.py").read_bytes(),
                (PROJECT_ROOT / "addon.py").read_bytes(),
            )
            self.assertEqual(
                Path(json.loads(stdout)["result"]["addon_path"]),
                target.resolve() / "addon.py",
            )

            marker = target / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            exit_code, stdout, stderr = run_cli(
                ["skill", "install", "--target", str(target)]
            )
            self.assertEqual(exit_code, 8)
            self.assertEqual(stdout, "")
            self.assertEqual(json.loads(stderr)["error"]["kind"], "local_io_error")

            exit_code, stdout, stderr = run_cli(
                ["skill", "install", "--target", str(target), "--force"]
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_skill_install_uses_codex_home_by_default(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            cli_module.os.environ, {"CODEX_HOME": directory}
        ):
            exit_code, stdout, stderr = run_cli(["skill", "install"])

            expected = Path(directory).resolve() / "skills/blender-mcp-cli"
            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(json.loads(stdout)["result"]["target"], str(expected))
            self.assertTrue((expected / "SKILL.md").is_file())
            self.assertTrue((expected / "LICENSE").is_file())
            self.assertTrue((expected / "addon.py").is_file())
            self.assertTrue((expected / "agents/openai.yaml").is_file())

    def test_skill_install_force_rejects_destination_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "installed-skill"
            target.mkdir()
            victim = root / "victim.txt"
            victim.write_text("unchanged", encoding="utf-8")
            try:
                (target / "SKILL.md").symlink_to(victim)
            except OSError as exc:
                self.skipTest(f"symbolic links are not available: {exc}")

            exit_code, stdout, stderr = run_cli(
                ["skill", "install", "--target", str(target), "--force"]
            )

            self.assertEqual(exit_code, 8)
            self.assertEqual(stdout, "")
            self.assertIn("symbolic link", json.loads(stderr)["error"]["message"])
            self.assertEqual(victim.read_text(encoding="utf-8"), "unchanged")

    def test_skill_install_force_rejects_symlinked_agents_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "installed-skill"
            target.mkdir()
            victim = root / "victim-agents"
            victim.mkdir()
            marker = victim / "keep.txt"
            marker.write_text("unchanged", encoding="utf-8")
            try:
                (target / "agents").symlink_to(victim, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links are not available: {exc}")

            exit_code, stdout, stderr = run_cli(
                ["skill", "install", "--target", str(target), "--force"]
            )

            self.assertEqual(exit_code, 8)
            self.assertEqual(stdout, "")
            self.assertIn("symbolic link", json.loads(stderr)["error"]["message"])
            self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")
            self.assertFalse((victim / "openai.yaml").exists())

    def test_skill_path_supports_pip_target_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repository"
            target = repository / ".smoke-target"
            module_file = target / "blender_mcp/cli.py"
            module_file.parent.mkdir(parents=True)
            module_file.touch()
            skill_path = (
                target / "share/blender-mcp-cli/skills/blender-mcp-cli"
            )
            (skill_path / "agents").mkdir(parents=True)
            (skill_path / "SKILL.md").write_text("skill", encoding="utf-8")
            (skill_path / "LICENSE").write_text("license", encoding="utf-8")
            (skill_path / "addon.py").write_text("addon", encoding="utf-8")
            (skill_path / "agents/openai.yaml").write_text(
                "interface: {}", encoding="utf-8"
            )
            misleading_source = repository / "skills/blender-mcp-cli"
            (misleading_source / "agents").mkdir(parents=True)
            (misleading_source / "SKILL.md").write_text(
                "wrong skill", encoding="utf-8"
            )
            (misleading_source / "LICENSE").write_text(
                "wrong license", encoding="utf-8"
            )
            (misleading_source / "agents/openai.yaml").write_text(
                "interface: {}", encoding="utf-8"
            )

            with mock.patch.object(cli_module, "__file__", str(module_file)), mock.patch(
                "blender_mcp.cli.distribution",
                side_effect=cli_module.PackageNotFoundError,
            ):
                resolved = cli_module._bundled_skill_path()

            self.assertEqual(resolved, skill_path.resolve())
            self.assertEqual(
                cli_module._bundled_addon_path(resolved),
                (skill_path / "addon.py").resolve(),
            )

    def test_skill_path_prefers_pip_target_data_when_target_is_named_src(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repository"
            target = repository / "src"
            module_file = target / "blender_mcp/cli.py"
            module_file.parent.mkdir(parents=True)
            module_file.touch()
            skill_path = (
                target / "share/blender-mcp-cli/skills/blender-mcp-cli"
            )
            (skill_path / "agents").mkdir(parents=True)
            (skill_path / "SKILL.md").write_text("skill", encoding="utf-8")
            (skill_path / "LICENSE").write_text("license", encoding="utf-8")
            (skill_path / "addon.py").write_text("addon", encoding="utf-8")
            (skill_path / "agents/openai.yaml").write_text(
                "interface: {}", encoding="utf-8"
            )
            misleading_source = repository / "skills/blender-mcp-cli"
            (misleading_source / "agents").mkdir(parents=True)
            (misleading_source / "SKILL.md").write_text(
                "wrong skill", encoding="utf-8"
            )
            (misleading_source / "LICENSE").write_text(
                "wrong license", encoding="utf-8"
            )
            (misleading_source / "agents/openai.yaml").write_text(
                "interface: {}", encoding="utf-8"
            )

            with mock.patch.object(cli_module, "__file__", str(module_file)), mock.patch(
                "blender_mcp.cli.distribution",
                side_effect=cli_module.PackageNotFoundError,
            ):
                resolved = cli_module._bundled_skill_path()

            self.assertEqual(resolved, skill_path.resolve())
            self.assertEqual(
                cli_module._bundled_addon_path(resolved),
                (skill_path / "addon.py").resolve(),
            )

    def test_scene_info_writes_json_envelope(self):
        response = {"status": "success", "result": {"name": "Scene", "object_count": 1}}
        with FakeBlenderServer(response) as server:
            exit_code, stdout, stderr = run_cli(
                ["--host", server.host, "--port", str(server.port), "scene", "info"]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["command"], "get_scene_info")
        self.assertEqual(payload["result"]["object_count"], 1)

    def test_raw_call_passes_json_params_without_mcp_translation(self):
        response = {"status": "success", "result": {"name": "Cube"}}
        with FakeBlenderServer(response) as server:
            exit_code, stdout, stderr = run_cli(
                [
                    "--host",
                    server.host,
                    "--port",
                    str(server.port),
                    "raw",
                    "call",
                    "get_object_info",
                    "--params",
                    '{"name":"Cube"}',
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            server.requests[0],
            {"type": "get_object_info", "params": {"name": "Cube"}},
        )
        self.assertEqual(json.loads(stdout)["result"]["name"], "Cube")

    def test_multiline_code_file_is_sent_verbatim(self):
        response = {"status": "success", "result": {"executed": True, "result": "ok\n"}}
        source = "for value in range(2):\n    print(value)\n"
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "script.py"
            script.write_text(source, encoding="utf-8")
            with FakeBlenderServer(response) as server:
                exit_code, stdout, stderr = run_cli(
                    [
                        "--host",
                        server.host,
                        "--port",
                        str(server.port),
                        "code",
                        "exec",
                        "--file",
                        str(script),
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(server.requests[0]["params"]["code"], source)
        self.assertTrue(json.loads(stdout)["result"]["executed"])

    def test_inner_handler_error_uses_operation_exit_code(self):
        response = {"status": "success", "result": {"error": "integration disabled"}}
        with FakeBlenderServer(response) as server:
            exit_code, stdout, stderr = run_cli(
                ["--host", server.host, "--port", str(server.port), "scene", "info"]
            )

        self.assertEqual(exit_code, 7)
        self.assertEqual(stdout, "")
        payload = json.loads(stderr)
        self.assertEqual(payload["error"]["kind"], "operation_error")

    def test_status_all_uses_five_serial_connections(self):
        def response_factory(request, index):
            return {"status": "success", "result": {"type": request["type"]}}

        with FakeBlenderServer(response_factory=response_factory, connections=5) as server:
            exit_code, stdout, stderr = run_cli(
                ["--host", server.host, "--port", str(server.port), "status", "all"]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(len(server.requests), 5)
        self.assertEqual(len(json.loads(stdout)["result"]), 5)

    def test_sketchfab_preview_decodes_image_file(self):
        image_bytes = b"not-a-real-image-but-valid-bytes"
        response = {
            "status": "success",
            "result": {
                "success": True,
                "image_data": base64.b64encode(image_bytes).decode("ascii"),
                "format": "png",
                "uid": "model-id",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "preview.png"
            with FakeBlenderServer(response) as server:
                exit_code, stdout, stderr = run_cli(
                    [
                        "--host",
                        server.host,
                        "--port",
                        str(server.port),
                        "sketchfab",
                        "preview",
                        "model-id",
                        "--output",
                        str(output),
                    ]
                )
            written = output.read_bytes()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(written, image_bytes)
        self.assertNotIn("image_data", json.loads(stdout)["result"])


if __name__ == "__main__":
    unittest.main()
