from __future__ import annotations

import json
import logging
from typing import Any, Callable

from backend.mcp.client import MCPClientManager
from backend.models import OperationRequest
from backend.tools.computer.tool import ComputerTool
from backend.tools.filesystem.tool import FilesystemTool
try:
    from backend.tools.knowledge.tool import KnowledgeTool
except ImportError:
    KnowledgeTool = None  # type: ignore[assignment,misc]
from backend.tools.scheduler.tool import SchedulerTool
from backend.tools.shell.tool import ShellTool
from backend.tools.wecom.tool import WeComTool
from backend.tools.email.tool import EmailTool


class ToolRouter:
    def __init__(
        self,
        mcp_manager: MCPClientManager | None = None,
        filesystem_allowed_dirs: list[str] | None = None,
        session_id: str | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
        vision_api_url: str = "",
        vision_api_key: str = "",
        vision_model: str = "",
    ) -> None:
        self._filesystem = FilesystemTool(allowed_directories=filesystem_allowed_dirs)
        self._shell = ShellTool()
        self._computer = ComputerTool()
        self._knowledge = KnowledgeTool() if KnowledgeTool is not None else None
        self._mcp_manager = mcp_manager or MCPClientManager()
        self._scheduler = SchedulerTool(session_id=session_id) if session_id else None
        self._wecom = WeComTool(
            event_callback=event_callback,
            vision_api_url=vision_api_url,
            vision_api_key=vision_api_key,
            vision_model=vision_model,
        )
        self._email = EmailTool()
        self._event_callback = event_callback

    def list_tools(self) -> list[dict]:
        """返回所有已注册工具的标准自描述信息列表。"""
        tools = [
            self._filesystem.describe(),
            self._shell.describe(),
            self._computer.describe(),
        ]
        if self._knowledge is not None:
            tools.append(self._knowledge.describe())
        tools.append(self._wecom.describe())
        tools.append(self._email.describe())
        if self._scheduler is not None:
            tools.append(self._scheduler.describe())
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

    _logger = logging.getLogger(__name__)

    def execute(self, operation: OperationRequest) -> dict:
        # [debug] 调试模式下记录工具调用详情
        try:
            from backend.debug import is_debug_enabled  # noqa: PLC0415
            if is_debug_enabled():
                self._logger.debug(
                    "[debug] 工具调用 → %s.%s | resource=%s | risk=%s | params=%s",
                    operation.tool, operation.action, operation.resource, operation.risk,
                    json.dumps(operation.params, ensure_ascii=False)[:300],
                )
        except Exception:  # noqa: BLE001
            pass

        result: dict
        if operation.tool == "filesystem":
            result = self._filesystem.execute(operation)
        elif operation.tool == "shell":
            result = self._shell.execute(operation)
        elif operation.tool == "scheduler":
            if self._scheduler is None:
                raise ValueError("scheduler 工具在非会话上下文中不可用")
            result = self._scheduler.execute(operation)
        elif operation.tool == "computer":
            result = self._computer.execute(operation)
        elif operation.tool == "knowledge":
            if self._knowledge is None:
                raise ValueError("knowledge 工具不可用（缺少 numpy 依赖）")
            result = self._knowledge.execute(operation)
        elif operation.tool == "wecom":
            result = self._wecom.execute(operation)
        elif operation.tool == "email":
            result = self._email.execute(operation)
        elif operation.tool == "mcp":
            result = self._execute_mcp(operation)
        else:
            raise ValueError(f"不支持的工具: {operation.tool}")

        # [debug] 调试模式下记录工具返回结果
        try:
            from backend.debug import is_debug_enabled  # noqa: PLC0415
            if is_debug_enabled():
                result_preview = json.dumps(result, ensure_ascii=False)
                if len(result_preview) > 500:
                    result_preview = result_preview[:500] + "..."
                self._logger.debug(
                    "[debug] 工具返回 ← %s.%s | ok=%s | result=%s",
                    operation.tool, operation.action,
                    result.get("ok", "?"),
                    result_preview,
                )
        except Exception:  # noqa: BLE001
            pass

        return result

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
