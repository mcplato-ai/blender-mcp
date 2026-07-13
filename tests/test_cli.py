from __future__ import annotations

import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from blender_mcp.cli import build_parser, main

from tests.fake_blender import FakeBlenderServer


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
