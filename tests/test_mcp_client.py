from __future__ import annotations

import unittest

from backend.mcp.client import MCPClientError, MCPClientManager, MCPServerClient


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def request(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        if method == "initialize":
            return {"protocolVersion": "2026-01-01"}
        if method == "tools/list":
            return {"tools": [{"name": "read_file"}]}
        if method == "tools/call":
            return {"content": [{"type": "text", "text": "ok"}], "isError": False}
        return {}


class TestMCPClient(unittest.TestCase):
    def test_server_client_initialize_and_call(self) -> None:
        transport = FakeTransport()
        client = MCPServerClient(server_name="fs", transport=transport)

        init_result = client.initialize()
        call_result = client.call_tool("read_file", {"path": "/tmp/a.txt"})

        self.assertIn("protocolVersion", init_result)
        self.assertFalse(call_result["isError"])

    def test_manager_register_and_call(self) -> None:
        manager = MCPClientManager()
        manager.register_server(MCPServerClient("fs", FakeTransport()))

        result = manager.call_tool("fs", "read_file", {"path": "/tmp/a.txt"})

        self.assertIn("content", result)

    def test_manager_unknown_server_raises(self) -> None:
        manager = MCPClientManager()

        with self.assertRaises(MCPClientError):
            manager.call_tool("missing", "read_file", {})


if __name__ == "__main__":
    unittest.main()
