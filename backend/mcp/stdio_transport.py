from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass, field
from queue import Queue, Empty
from typing import Any, Callable, TextIO

from backend.mcp.client import MCPClientError, MCPTransport


def _default_process_factory(
    command: list[str], cwd: str | None, env: dict[str, str] | None
) -> "StdIOProcessHandle":
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdin is None or process.stdout is None:
        process.kill()
        raise MCPClientError("无法启动 MCP 进程")
    return StdIOProcessHandle(
        stdin=process.stdin,
        stdout=process.stdout,
        stderr=process.stderr,
        poll=process.poll,
        wait=process.wait,
        terminate=process.terminate,
        kill=process.kill,
    )


@dataclass(slots=True)
class StdIOProcessHandle:
    stdin: Any
    stdout: Any
    stderr: Any
    poll: Callable[[], int | None]
    wait: Callable[[float | None], int]
    terminate: Callable[[], None]
    kill: Callable[[], None]


@dataclass(slots=True)
class StdIOTransport(MCPTransport):
    command: list[str]
    cwd: str | None = None
    env: dict[str, str] | None = None
    timeout: float = 30.0
    process_factory: Callable[[list[str], str | None, dict[str, str] | None], StdIOProcessHandle] = field(default=_default_process_factory)
    _process: StdIOProcessHandle | None = field(init=False, default=None)
    _stderr_lines: list[str] = field(init=False, default_factory=list)
    _stderr_thread: threading.Thread | None = field(init=False, default=None)
    _request_id: int = field(init=False, default=0)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            last_error: Exception | None = None
            for attempt in range(2):
                try:
                    return self._request_once(method, params)
                except (BrokenPipeError, ConnectionResetError, MCPClientError) as exc:
                    last_error = exc
                    self._restart_process()
                    if attempt == 0:
                        continue
                    raise self._wrap_with_stderr(exc) from exc
            if last_error is not None:
                raise self._wrap_with_stderr(last_error) from last_error
            raise MCPClientError("MCP 请求失败")

    def close(self) -> None:
        if self._process is None:
            return
        try:
            self._process.terminate()
            try:
                self._process.wait(1.0)
            except Exception:  # noqa: BLE001
                self._process.kill()
                self._process.wait(1.0)
        finally:
            self._close_handles(self._process)
            self._process = None
            self._stderr_thread = None

    def _ensure_process(self) -> StdIOProcessHandle:
        if self._process is not None:
            if self._process.poll() is None:
                return self._process
            self._restart_process()
        self._process = self.process_factory(self.command, self.cwd, self.env)
        self._stderr_lines = []
        self._start_stderr_reader(self._process.stderr)
        return self._process

    def _restart_process(self) -> None:
        self.close()
        self._process = self.process_factory(self.command, self.cwd, self.env)
        self._stderr_lines = []
        self._start_stderr_reader(self._process.stderr)

    def _request_once(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        process = self._ensure_process()
        self._request_id += 1
        request_id = self._request_id
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        self._write_message(process.stdin, payload)
        response = self._read_message_with_timeout(process.stdout)
        if response.get("id") != request_id:
            raise MCPClientError("MCP response id mismatch")
        if "error" in response:
            raise MCPClientError(self._format_error(response["error"]))
        result = response.get("result")
        if not isinstance(result, dict):
            raise MCPClientError("MCP response result must be an object")
        return result

    def _write_message(self, stdin: TextIO, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        message = b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body
        stdin.write(message)
        stdin.flush()

    def _read_message_with_timeout(self, stdout: TextIO) -> dict[str, Any]:
        response_queue: Queue[dict[str, Any] | Exception] = Queue(maxsize=1)

        def reader() -> None:
            try:
                response_queue.put(self._read_message(stdout), block=False)
            except Exception as exc:  # noqa: BLE001
                response_queue.put(exc, block=False)

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        thread.join(self.timeout)
        if thread.is_alive():
            self._kill_process()
            raise MCPClientError(f"MCP 请求超时: {self.timeout} 秒")

        try:
            payload = response_queue.get_nowait()
        except Empty as exc:
            raise MCPClientError("MCP 响应为空") from exc

        if isinstance(payload, Exception):
            raise payload
        return payload

    def _read_message(self, stdout: TextIO) -> dict[str, Any]:
        content_length = self._read_content_length(stdout)
        if content_length is None:
            raise MCPClientError("MCP server closed the stream unexpectedly")
        body = stdout.read(content_length)
        if body is None or len(body) == 0:
            raise MCPClientError("MCP server returned an empty body")
        if isinstance(body, str):
            body = body.encode("utf-8")
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise MCPClientError(f"无法解析 MCP 响应: {exc}") from exc

    def _read_content_length(self, stdout: TextIO) -> int | None:
        headers: list[str] = []
        while True:
            line = stdout.readline()
            if line in {b"", ""}:
                return None
            if isinstance(line, bytes):
                line = line.decode("utf-8")
            line = line.strip("\r\n")
            if not line:
                break
            headers.append(line)

        for header in headers:
            key, separator, value = header.partition(":")
            if key.lower() == "content-length" and separator:
                try:
                    return int(value.strip())
                except ValueError as exc:
                    raise MCPClientError("MCP 响应头 Content-Length 无效") from exc

        raise MCPClientError("MCP 响应缺少 Content-Length 头")

    def _format_error(self, error: Any) -> str:
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message", "MCP error")
            return f"MCP error {code}: {message}" if code is not None else f"MCP error: {message}"
        return f"MCP error: {error}"

    def _start_stderr_reader(self, stderr: TextIO | None) -> None:
        if stderr is None:
            return

        def drain() -> None:
            while self._process is not None:
                try:
                    line = stderr.readline()
                except Exception:  # noqa: BLE001
                    break
                if line in {b"", ""}:
                    break
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")
                self._stderr_lines.append(line.rstrip("\r\n"))

        thread = threading.Thread(target=drain, daemon=True)
        self._stderr_thread = thread
        thread.start()

    def _kill_process(self) -> None:
        if self._process is None:
            return
        try:
            self._process.kill()
            try:
                self._process.wait(1.0)
            except Exception:  # noqa: BLE001
                pass
        finally:
            self._close_handles(self._process)
            self._process = None

    def _close_handles(self, process: StdIOProcessHandle) -> None:
        for handle in (process.stdin, process.stdout, process.stderr):
            close = getattr(handle, "close", None)
            if callable(close):
                close()

    def _wrap_with_stderr(self, exc: Exception) -> MCPClientError:
        stderr_tail = self._stderr_lines[-5:]
        if stderr_tail:
            return MCPClientError(f"{exc}; stderr: {' | '.join(stderr_tail)}")
        return MCPClientError(str(exc))
