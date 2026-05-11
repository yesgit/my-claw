from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class MCPClientError(RuntimeError):
    pass


class MCPTransport(Protocol):
    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send one MCP request and return the response payload."""


@dataclass(slots=True)
class MCPServerClient:
    server_name: str
    transport: MCPTransport

    def initialize(self, client_name: str = "my-claw", client_version: str = "0.1") -> dict[str, Any]:
        return self.transport.request(
            "initialize",
            {
                "clientInfo": {
                    "name": client_name,
                    "version": client_version,
                }
            },
        )

    def list_tools(self) -> list[dict[str, Any]]:
        response = self.transport.request("tools/list", {})
        tools = response.get("tools")
        if not isinstance(tools, list):
            raise MCPClientError(f"server {self.server_name} 返回了无效 tools/list 响应")
        return tools

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self.transport.request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
        )
        if not isinstance(response, dict):
            raise MCPClientError(f"server {self.server_name} 返回了无效 tools/call 响应")
        return response


class MCPClientManager:
    def __init__(self) -> None:
        self._servers: dict[str, MCPServerClient] = {}

    def register_server(self, client: MCPServerClient) -> None:
        self._servers[client.server_name] = client

    def get_server(self, server_name: str) -> MCPServerClient:
        server = self._servers.get(server_name)
        if server is None:
            raise MCPClientError(f"未注册的 MCP server: {server_name}")
        return server

    def list_servers(self) -> list[str]:
        return sorted(self._servers.keys())

    def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        return self.get_server(server_name).list_tools()

    def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        server = self.get_server(server_name)
        return server.call_tool(tool_name=tool_name, arguments=arguments)

    def close_all(self) -> None:
        for server in self._servers.values():
            transport = getattr(server, "transport", None)
            close = getattr(transport, "close", None)
            if callable(close):
                close()
