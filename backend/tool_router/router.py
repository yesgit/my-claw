from __future__ import annotations

from backend.mcp.client import MCPClientManager
from backend.models import OperationRequest
from backend.tools.filesystem.tool import FilesystemTool
from backend.tools.shell.tool import ShellTool


class ToolRouter:
    def __init__(
        self,
        mcp_manager: MCPClientManager | None = None,
        filesystem_allowed_dirs: list[str] | None = None,
    ) -> None:
        self._filesystem = FilesystemTool(allowed_directories=filesystem_allowed_dirs)
        self._shell = ShellTool()
        self._mcp_manager = mcp_manager or MCPClientManager()

    def list_tools(self) -> list[dict]:
        """返回所有已注册工具的标准自描述信息列表。"""
        tools = [
            self._filesystem.describe(),
            self._shell.describe(),
        ]
        # 添加 MCP 工具
        for server_name in self._mcp_manager.list_servers():
            try:
                mcp_tools = self._mcp_manager.list_tools(server_name)
                for tool in mcp_tools:
                    tool_name = tool.get("name", "unknown")
                    tools.append({
                        # 新版统一字段
                        "tool": f"mcp.{server_name}.{tool_name}",
                        "type": "mcp",
                        "actions": [{"name": "call_tool", "default_risk": "medium"}],
                        "input_schema": tool.get("inputSchema", {}),
                        # 兼容旧字段
                        "tool_name": f"mcp.{server_name}.{tool.get('name', 'unknown')}",
                        "description": tool.get("description", f"MCP tool from {server_name}"),
                        "server": server_name,
                        "mcp_tool_name": tool_name,
                    })
            except Exception:  # noqa: BLE001
                pass
        return tools

    def execute(self, operation: OperationRequest) -> dict:
        if operation.tool == "filesystem":
            return self._filesystem.execute(operation)
        if operation.tool == "shell":
            return self._shell.execute(operation)
        if operation.tool == "mcp":
            return self._execute_mcp(operation)

        raise ValueError(f"不支持的工具: {operation.tool}")

    def _execute_mcp(self, operation: OperationRequest) -> dict:
        server_name, tool_name = self._parse_mcp_resource(operation.resource)
        result = self._mcp_manager.call_tool(
            server_name=server_name,
            tool_name=tool_name,
            arguments=operation.params,
        )
        return {
            "ok": True,
            "tool": "mcp",
            "server": server_name,
            "action": tool_name,
            "resource": operation.resource,
            "result": result,
        }

    def _parse_mcp_resource(self, resource: str) -> tuple[str, str]:
        prefix = "mcp://"
        if not resource.startswith(prefix):
            raise ValueError("mcp 操作的 resource 必须是 mcp://server/tool 格式")

        location = resource[len(prefix) :]
        parts = location.split("/", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError("mcp 操作的 resource 必须是 mcp://server/tool 格式")
        return parts[0], parts[1]
