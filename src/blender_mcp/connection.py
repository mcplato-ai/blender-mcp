"""Direct TCP client for the Blender MCP add-on socket protocol."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any


DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9876
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_RESPONSE_TIMEOUT = 180.0
DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024 * 1024


class BlenderClientError(Exception):
    """Base class for direct Blender client errors."""

    kind = "client_error"
    exit_code = 1

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message)
        self.details = details


class BlenderConnectionError(BlenderClientError):
    """The CLI could not connect to or write to Blender."""

    kind = "connection_error"
    exit_code = 3


class BlenderTimeoutError(BlenderClientError):
    """Blender did not connect or respond before the configured timeout."""

    kind = "timeout"
    exit_code = 4


class BlenderProtocolError(BlenderClientError):
    """Blender returned a response that does not match the socket protocol."""

    kind = "protocol_error"
    exit_code = 5


class BlenderCommandError(BlenderClientError):
    """Blender accepted the request but reported an execution error."""

    kind = "blender_error"
    exit_code = 6


@dataclass(slots=True)
class BlenderClient:
    """Send one command at a time to the unmodified Blender add-on.

    The add-on protocol has no message delimiter or request ID. A fresh TCP
    connection per call avoids response interleaving and makes CLI failures
    deterministic. Mutating commands are never retried automatically.
    """

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    response_timeout: float = DEFAULT_RESPONSE_TIMEOUT
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    buffer_size: int = 8192

    def call(self, command_type: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a Blender add-on command and return its result field."""
        if not command_type or not isinstance(command_type, str):
            raise ValueError("command_type must be a non-empty string")
        if params is not None and not isinstance(params, dict):
            raise ValueError("params must be a JSON object")

        request = {
            "type": command_type,
            "params": params or {},
        }
        # ASCII escaping avoids splitting raw UTF-8 code points across recv calls
        # in the add-on, which decodes its accumulated buffer on every chunk.
        payload = json.dumps(request, ensure_ascii=True, separators=(",", ":")).encode(
            "utf-8"
        )

        try:
            sock = socket.create_connection(
                (self.host, self.port), timeout=self.connect_timeout
            )
        except socket.timeout as exc:
            raise BlenderTimeoutError(
                f"Timed out connecting to Blender at {self.host}:{self.port}"
            ) from exc
        except OSError as exc:
            raise BlenderConnectionError(
                f"Could not connect to Blender at {self.host}:{self.port}: {exc}"
            ) from exc

        with sock:
            sock.settimeout(self.response_timeout)
            try:
                sock.sendall(payload)
            except socket.timeout as exc:
                raise BlenderTimeoutError(
                    "Timed out while sending the command to Blender; execution state is unknown"
                ) from exc
            except OSError as exc:
                raise BlenderConnectionError(
                    f"Failed to send the command to Blender: {exc}"
                ) from exc

            response = self._receive_response(sock)

        status = response.get("status")
        if status == "error":
            raise BlenderCommandError(
                str(response.get("message", "Unknown Blender error")),
                details=response,
            )
        if status != "success":
            raise BlenderProtocolError(
                "Blender response is missing status='success' or status='error'",
                details=response,
            )
        return response.get("result")

    def _receive_response(self, sock: socket.socket) -> dict[str, Any]:
        data = bytearray()

        while True:
            try:
                chunk = sock.recv(self.buffer_size)
            except socket.timeout as exc:
                received = f" after receiving {len(data)} bytes" if data else ""
                raise BlenderTimeoutError(
                    "Timed out waiting for Blender to return a complete JSON response"
                    f"{received}; the command may still be running"
                ) from exc
            except OSError as exc:
                raise BlenderConnectionError(
                    f"Connection to Blender failed while receiving a response: {exc}"
                ) from exc

            if not chunk:
                if not data:
                    raise BlenderProtocolError(
                        "Blender closed the connection without returning a response"
                    )
                raise BlenderProtocolError(
                    "Blender closed the connection before returning complete JSON",
                    details={"received_bytes": len(data)},
                )

            data.extend(chunk)
            if len(data) > self.max_response_bytes:
                raise BlenderProtocolError(
                    f"Blender response exceeded {self.max_response_bytes} bytes"
                )

            try:
                decoded = data.decode("utf-8")
                response = json.loads(decoded)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

            if not isinstance(response, dict):
                raise BlenderProtocolError(
                    "Blender response must be a JSON object", details=response
                )
            return response
