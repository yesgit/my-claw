from __future__ import annotations

import io
import json
import threading
import time
import unittest

from backend.mcp.client import MCPClientError
from backend.mcp.stdio_transport import StdIOProcessHandle, StdIOTransport


class BytesIOStdout:
    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)

    def readline(self) -> bytes:
        return self._buffer.readline()

    def read(self, n: int = -1) -> bytes:
        return self._buffer.read(n)


class BytesIOStdin:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()

    def write(self, data: bytes) -> int:
        return self.buffer.write(data)

    def flush(self) -> None:
        return None


class FakeProcessFactory:
    def __init__(self, response_payload: dict) -> None:
        self.stdin = BytesIOStdin()
        response_body = json.dumps(response_payload, ensure_ascii=False).encode("utf-8")
        self.stdout = BytesIOStdout(
            b"Content-Length: " + str(len(response_body)).encode("ascii") + b"\r\n\r\n" + response_body
        )

    def __call__(self, command: list[str], cwd: str | None, env: dict[str, str] | None) -> StdIOProcessHandle:
        return StdIOProcessHandle(
            stdin=self.stdin,
            stdout=self.stdout,
            stderr=io.BytesIO(),
            poll=lambda: None,
            wait=lambda timeout=None: 0,
            terminate=lambda: None,
            kill=lambda: None,
        )


class SlowStdout:
    def __init__(self, response: bytes, ready: threading.Event) -> None:
        self._buffer = io.BytesIO(response)
        self._ready = ready

    def readline(self) -> bytes:
        self._ready.wait(timeout=1.0)
        return self._buffer.readline()

    def read(self, n: int = -1) -> bytes:
        self._ready.wait(timeout=1.0)
        return self._buffer.read(n)


class TestStdIOTransport(unittest.TestCase):
    def test_request_round_trip(self) -> None:
        factory = FakeProcessFactory(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"tools": [{"name": "read_file"}]},
            }
        )
        transport = StdIOTransport(command=["fake"], process_factory=factory)

        result = transport.request("tools/list", {})
        written = factory.stdin.buffer.getvalue().decode("utf-8")

        self.assertEqual(result["tools"][0]["name"], "read_file")
        self.assertIn("tools/list", written)
        self.assertIn("Content-Length", written)

    def test_missing_content_length_raises(self) -> None:
        class BadFactory:
            def __call__(self, command: list[str], cwd: str | None, env: dict[str, str] | None) -> StdIOProcessHandle:
                return StdIOProcessHandle(
                    stdin=BytesIOStdin(),
                    stdout=BytesIOStdout(b"{}"),
                    stderr=io.BytesIO(),
                    poll=lambda: None,
                    wait=lambda timeout=None: 0,
                    terminate=lambda: None,
                    kill=lambda: None,
                )

        transport = StdIOTransport(command=["fake"], process_factory=BadFactory())

        with self.assertRaises(MCPClientError):
            transport.request("tools/list", {})

    def test_timeout_raises(self) -> None:
        ready = threading.Event()

        class SlowFactory:
            def __call__(self, command: list[str], cwd: str | None, env: dict[str, str] | None) -> StdIOProcessHandle:
                return StdIOProcessHandle(
                    stdin=BytesIOStdin(),
                    stdout=SlowStdout(b"Content-Length: 2\r\n\r\n{}", ready),
                    stderr=io.BytesIO(),
                    poll=lambda: None,
                    wait=lambda timeout=None: 0,
                    terminate=lambda: None,
                    kill=lambda: None,
                )

        transport = StdIOTransport(command=["fake"], timeout=0.05, process_factory=SlowFactory())

        start = time.time()
        with self.assertRaises(MCPClientError) as ctx:
            transport.request("tools/list", {})
        elapsed = time.time() - start

        self.assertIn("超时", str(ctx.exception))
        self.assertLess(elapsed, 0.5)

    def test_retry_once_then_success(self) -> None:
        class FlakyFactory:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(self, command: list[str], cwd: str | None, env: dict[str, str] | None) -> StdIOProcessHandle:
                self.calls += 1
                if self.calls == 1:
                    return StdIOProcessHandle(
                        stdin=BytesIOStdin(),
                        stdout=BytesIOStdout(b""),
                        stderr=io.BytesIO(b"first failure\n"),
                        poll=lambda: None,
                        wait=lambda timeout=None: 0,
                        terminate=lambda: None,
                        kill=lambda: None,
                    )

                response_body = json.dumps(
                    {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}},
                    ensure_ascii=False,
                ).encode("utf-8")
                return StdIOProcessHandle(
                    stdin=BytesIOStdin(),
                    stdout=BytesIOStdout(
                        b"Content-Length: " + str(len(response_body)).encode("ascii") + b"\r\n\r\n" + response_body
                    ),
                    stderr=io.BytesIO(),
                    poll=lambda: None,
                    wait=lambda timeout=None: 0,
                    terminate=lambda: None,
                    kill=lambda: None,
                )

        factory = FlakyFactory()
        transport = StdIOTransport(command=["fake"], process_factory=factory)

        result = transport.request("tools/list", {})

        self.assertTrue(result["ok"])
        self.assertEqual(factory.calls, 2)

    def test_failure_includes_stderr_tail(self) -> None:
        class ErrorFactory:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(self, command: list[str], cwd: str | None, env: dict[str, str] | None) -> StdIOProcessHandle:
                self.calls += 1
                return StdIOProcessHandle(
                    stdin=BytesIOStdin(),
                    stdout=BytesIOStdout(b""),
                    stderr=io.BytesIO(b"boom line 1\nboom line 2\n"),
                    poll=lambda: None,
                    wait=lambda timeout=None: 0,
                    terminate=lambda: None,
                    kill=lambda: None,
                )

        transport = StdIOTransport(command=["fake"], process_factory=ErrorFactory())

        with self.assertRaises(MCPClientError) as ctx:
            transport.request("tools/list", {})

        self.assertIn("stderr", str(ctx.exception))
        self.assertIn("boom line 2", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
