from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def write_response(payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def read_request() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.decode("utf-8").strip("\r\n")
        if not line:
            break
        key, _, value = line.partition(":")
        headers[key.lower()] = value.strip()

    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "read_file",
            "description": "Read a text file from disk.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        {
            "name": "list_dir",
            "description": "List directory contents.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    ]


def handle_tools_call(arguments: dict[str, Any]) -> dict[str, Any]:
    name = arguments.get("name")
    tool_args = arguments.get("arguments", {})
    if name == "read_file":
        path = Path(tool_args["path"])
        return {"content": [{"type": "text", "text": path.read_text(encoding="utf-8")}]}
    if name == "list_dir":
        path = Path(tool_args["path"])
        entries = sorted(child.name for child in path.iterdir())
        return {"content": [{"type": "text", "text": "\n".join(entries)}]}
    return {"content": [{"type": "text", "text": f"unsupported tool: {name}"}], "isError": True}


def main() -> None:
    while True:
        request = read_request()
        if request is None:
            break

        method = request.get("method")
        request_id = request.get("id")

        if method == "initialize":
            write_response(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2026-01-01",
                        "serverInfo": {"name": "demo-filesystem", "version": "0.1"},
                    },
                }
            )
            continue

        if method == "tools/list":
            write_response(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"tools": list_tools()},
                }
            )
            continue

        if method == "tools/call":
            write_response(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": handle_tools_call(request.get("params", {})),
                }
            )
            continue

        write_response(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        )


if __name__ == "__main__":
    main()
