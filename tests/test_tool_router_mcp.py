from __future__ import annotations

import unittest

from backend.mcp.client import MCPClientManager, MCPServerClient
from backend.models import OperationRequest
from backend.tool_router.router import ToolRouter


class FakeTransport:
    def request(self, method: str, params: dict) -> dict:
        if method == "tools/call":
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"called {params['name']}",
                    }
                ],
                "isError": False,
            }
        if method == "tools/list":
            return {"tools": [{"name": "read_file"}]}
        return {"ok": True}


class TestToolRouterMCP(unittest.TestCase):
    def test_list_tools_schema_contains_unified_fields(self) -> None:
        manager = MCPClientManager()
        manager.register_server(MCPServerClient("filesystem", FakeTransport()))
        router = ToolRouter(mcp_manager=manager)

        tools = router.list_tools()

        fs_tool = next(item for item in tools if item.get("tool") == "filesystem")
        self.assertEqual(fs_tool["type"], "local")
        self.assertTrue(any(action["name"] == "write_file" for action in fs_tool["actions"]))

        mcp_tool = next(item for item in tools if item.get("type") == "mcp")
        self.assertEqual(mcp_tool["tool"], "mcp.filesystem.read_file")
        self.assertEqual(mcp_tool["mcp_tool_name"], "read_file")
        self.assertTrue(any(action["name"] == "call_tool" for action in mcp_tool["actions"]))

    def test_execute_mcp_tool(self) -> None:
        manager = MCPClientManager()
        manager.register_server(MCPServerClient("filesystem", FakeTransport()))
        router = ToolRouter(mcp_manager=manager)
        operation = OperationRequest(
            tool="mcp",
            action="call_tool",
            resource="mcp://filesystem/read_file",
            params={"path": "/tmp/a.txt"},
        )

        result = router.execute(operation)

        self.assertTrue(result["ok"])
        self.assertEqual(result["server"], "filesystem")
        self.assertEqual(result["action"], "read_file")

    def test_invalid_resource_raises(self) -> None:
        router = ToolRouter(mcp_manager=MCPClientManager())
        operation = OperationRequest(
            tool="mcp",
            action="call_tool",
            resource="invalid://filesystem/read_file",
            params={},
        )

        with self.assertRaises(ValueError):
            router.execute(operation)


if __name__ == "__main__":
    unittest.main()
