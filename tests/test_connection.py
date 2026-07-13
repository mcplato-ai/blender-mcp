from __future__ import annotations

import unittest

from blender_mcp.connection import (
    BlenderClient,
    BlenderCommandError,
    BlenderProtocolError,
    BlenderTimeoutError,
)

from tests.fake_blender import FakeBlenderServer


class BlenderClientTests(unittest.TestCase):
    def test_sends_command_and_receives_chunked_response(self):
        response = {
            "status": "success",
            "result": {"name": "场景", "objects": ["Cube"]},
        }
        with FakeBlenderServer(response, chunks=7) as server:
            client = BlenderClient(host=server.host, port=server.port)
            result = client.call("get_scene_info")

        self.assertEqual(result, response["result"])
        self.assertEqual(
            server.requests,
            [{"type": "get_scene_info", "params": {}}],
        )

    def test_request_uses_ascii_escaped_json(self):
        response = {"status": "success", "result": {"executed": True}}
        with FakeBlenderServer(response) as server:
            client = BlenderClient(host=server.host, port=server.port)
            client.call("execute_code", {"code": "print('你好')"})

        self.assertIn(b"\\u4f60\\u597d", server.raw_requests[0])
        self.assertNotIn("你好".encode("utf-8"), server.raw_requests[0])

    def test_outer_blender_error_has_distinct_exception(self):
        response = {"status": "error", "message": "Unknown command type: nope"}
        with FakeBlenderServer(response) as server:
            client = BlenderClient(host=server.host, port=server.port)
            with self.assertRaises(BlenderCommandError) as raised:
                client.call("nope")

        self.assertEqual(raised.exception.exit_code, 6)
        self.assertIn("Unknown command", str(raised.exception))

    def test_timeout_does_not_retry(self):
        response = {"status": "success", "result": {"ok": True}}
        with FakeBlenderServer(response, delay=0.2) as server:
            client = BlenderClient(
                host=server.host,
                port=server.port,
                response_timeout=0.05,
            )
            with self.assertRaises(BlenderTimeoutError):
                client.call("execute_code", {"code": "print('once')"})

        self.assertEqual(len(server.requests), 1)

    def test_incomplete_json_is_protocol_error(self):
        with FakeBlenderServer(raw_response=b'{"status":"success"') as server:
            client = BlenderClient(host=server.host, port=server.port)
            with self.assertRaises(BlenderProtocolError):
                client.call("get_scene_info")

    def test_non_object_response_is_protocol_error(self):
        with FakeBlenderServer(["not", "an", "object"]) as server:
            client = BlenderClient(host=server.host, port=server.port)
            with self.assertRaises(BlenderProtocolError):
                client.call("get_scene_info")


if __name__ == "__main__":
    unittest.main()
