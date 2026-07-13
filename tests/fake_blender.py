from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable
from typing import Any


ResponseFactory = Callable[[dict[str, Any], int], Any]


class FakeBlenderServer:
    def __init__(
        self,
        response: Any = None,
        *,
        response_factory: ResponseFactory | None = None,
        chunks: int = 1,
        delay: float = 0.0,
        connections: int = 1,
        raw_response: bytes | None = None,
    ):
        self.response = response
        self.response_factory = response_factory
        self.chunks = chunks
        self.delay = delay
        self.connections = connections
        self.raw_response = raw_response
        self.requests: list[dict[str, Any]] = []
        self.raw_requests: list[bytes] = []
        self.error: Exception | None = None
        self._ready = threading.Event()
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self.host = "127.0.0.1"
        self.port = 0

    def __enter__(self):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.host, 0))
        self._socket.listen()
        self._socket.settimeout(2.0)
        self.port = self._socket.getsockname()[1]
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=1.0)
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self._socket is not None:
            self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self.error is not None and exc is None:
            raise self.error

    def _run(self):
        self._ready.set()
        try:
            for index in range(self.connections):
                client, _ = self._socket.accept()
                with client:
                    request_bytes = self._receive_json(client)
                    request = json.loads(request_bytes.decode("utf-8"))
                    self.raw_requests.append(request_bytes)
                    self.requests.append(request)
                    if self.delay:
                        time.sleep(self.delay)
                    if self.raw_response is not None:
                        payload = self.raw_response
                    else:
                        response = (
                            self.response_factory(request, index)
                            if self.response_factory is not None
                            else self.response
                        )
                        payload = json.dumps(response).encode("utf-8")
                    self._send_chunks(client, payload)
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            if self._socket is not None and self._socket.fileno() != -1:
                self.error = exc

    @staticmethod
    def _receive_json(client: socket.socket) -> bytes:
        data = bytearray()
        while True:
            chunk = client.recv(8192)
            if not chunk:
                raise RuntimeError("client closed before sending complete JSON")
            data.extend(chunk)
            try:
                json.loads(data.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            return bytes(data)

    def _send_chunks(self, client: socket.socket, payload: bytes) -> None:
        if self.chunks <= 1:
            client.sendall(payload)
            return
        chunk_size = max(1, len(payload) // self.chunks)
        for offset in range(0, len(payload), chunk_size):
            client.sendall(payload[offset : offset + chunk_size])
