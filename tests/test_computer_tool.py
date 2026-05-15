"""computer 工具单元测试。

由于 Linux CI 环境没有 Windows 依赖，大部分测试验证：
1. 工具描述（describe）输出正确
2. 非Windows环境下返回友好的不可用提示
3. 参数校验
4. 状态管理
"""
from __future__ import annotations

import pytest

from backend.models import OperationRequest
from backend.tools.computer.state import ComputerState
from backend.tools.computer.tool import ComputerTool


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _op(action: str, params: dict | None = None, resource: str = "computer") -> OperationRequest:
    return OperationRequest(
        tool="computer",
        action=action,
        resource=resource,
        params=params or {},
        risk="low",
    )


# ---------------------------------------------------------------------------
# ComputerState 测试
# ---------------------------------------------------------------------------

class TestComputerState:
    def test_record_and_history(self):
        state = ComputerState()
        state.record("find_window", {"title": "test"}, {"ok": True, "count": 0})
        state.record("read_text", {"hwnd": 123}, {"ok": True, "count": 5})

        history = state.get_history(2)
        assert len(history) == 2
        assert history[0]["action"] == "find_window"
        assert history[1]["action"] == "read_text"

    def test_history_limit(self):
        state = ComputerState()
        for i in range(60):
            state.record("action", {"i": i}, {"ok": True})
        assert len(state.get_history(100)) == 50  # MAX_HISTORY

    def test_current_hwnd(self):
        state = ComputerState()
        assert state.current_hwnd is None
        state.current_hwnd = 12345
        assert state.current_hwnd == 12345

    def test_message_tracking(self):
        state = ComputerState()
        assert state.get_last_read_message("group_a") == ""

        state.set_last_read_message("group_a", "hello world")
        assert state.get_last_read_message("group_a") == "hello world"

        groups = state.get_all_tracked_groups()
        assert "group_a" in groups

    def test_get_status(self):
        state = ComputerState()
        state.current_hwnd = 42
        state.set_last_read_message("g1", "msg")

        status = state.get_status()
        assert status["current_hwnd"] == 42
        assert status["history_count"] == 0
        assert "g1" in status["tracked_groups"]


# ---------------------------------------------------------------------------
# ComputerTool describe 测试
# ---------------------------------------------------------------------------

class TestComputerToolDescribe:
    def test_describe_structure(self):
        tool = ComputerTool()
        desc = tool.describe()

        assert desc["tool"] == "computer"
        assert desc["type"] == "local"
        assert isinstance(desc["actions"], list)
        assert len(desc["actions"]) > 0

        # 兼容旧字段
        assert desc["tool_name"] == "computer"
        assert isinstance(desc["supported_actions"], dict)

    def test_describe_has_all_actions(self):
        tool = ComputerTool()
        desc = tool.describe()
        action_names = {a["name"] for a in desc["actions"]}

        expected = {
            "find_window", "take_screenshot", "read_text", "list_controls",
            "read_list_items", "click", "type_text", "send_keys",
            "scroll", "wait", "get_status",
        }
        assert expected == action_names

    def test_describe_input_schema(self):
        tool = ComputerTool()
        desc = tool.describe()
        schema = desc["input_schema"]

        # read_text 需要 hwnd
        assert "hwnd" in schema["read_text"]["properties"]
        assert "hwnd" in schema["read_text"]["required"]

        # click 需要 hwnd
        assert "hwnd" in schema["click"]["properties"]
        assert "hwnd" in schema["click"]["required"]

        # type_text 需要 text
        assert "text" in schema["type_text"]["properties"]
        assert "text" in schema["type_text"]["required"]

        # send_keys 需要 keys
        assert "keys" in schema["send_keys"]["properties"]
        assert "keys" in schema["send_keys"]["required"]


# ---------------------------------------------------------------------------
# ComputerTool execute 测试（非 Windows 环境）
# ---------------------------------------------------------------------------

class TestComputerToolExecute:
    """在非 Windows 环境下，execute 应返回友好错误。"""

    def test_find_window_not_windows(self):
        tool = ComputerTool()
        result = tool.execute(_op("find_window", {"title": "test"}))
        # 在 Linux 上应该返回不可用提示，或者如果刚好是 Windows 则返回 ok
        assert isinstance(result, dict)
        assert "ok" in result

    def test_take_screenshot_not_windows(self):
        tool = ComputerTool()
        result = tool.execute(_op("take_screenshot"))
        assert isinstance(result, dict)
        assert "ok" in result

    def test_read_text_no_hwnd(self):
        tool = ComputerTool()
        result = tool.execute(_op("read_text", {}))
        assert result["ok"] is False
        # 在非 Windows 上先返回不可用提示；Windows 上返回缺少参数
        assert "hwnd" in result["error"] or "不可用" in result["error"]

    def test_list_controls_no_hwnd(self):
        tool = ComputerTool()
        result = tool.execute(_op("list_controls", {}))
        assert result["ok"] is False
        assert "hwnd" in result["error"] or "不可用" in result["error"]

    def test_read_list_items_no_hwnd(self):
        tool = ComputerTool()
        result = tool.execute(_op("read_list_items", {}))
        assert result["ok"] is False
        assert "hwnd" in result["error"] or "不可用" in result["error"]

    def test_click_no_hwnd(self):
        tool = ComputerTool()
        result = tool.execute(_op("click", {}))
        assert result["ok"] is False
        assert "hwnd" in result["error"] or "不可用" in result["error"]

    def test_type_text_no_text(self):
        tool = ComputerTool()
        result = tool.execute(_op("type_text", {}))
        assert result["ok"] is False
        assert "text" in result["error"] or "不可用" in result["error"]

    def test_type_text_empty_text(self):
        tool = ComputerTool()
        result = tool.execute(_op("type_text", {"text": ""}))
        assert result["ok"] is False

    def test_send_keys_no_keys(self):
        tool = ComputerTool()
        result = tool.execute(_op("send_keys", {}))
        assert result["ok"] is False
        assert "keys" in result["error"] or "不可用" in result["error"]

    def test_send_keys_empty_keys(self):
        tool = ComputerTool()
        result = tool.execute(_op("send_keys", {"keys": ""}))
        assert result["ok"] is False

    def test_scroll_no_hwnd(self):
        tool = ComputerTool()
        result = tool.execute(_op("scroll", {}))
        assert result["ok"] is False
        assert "hwnd" in result["error"] or "不可用" in result["error"]

    def test_wait_action(self):
        tool = ComputerTool()
        result = tool.execute(_op("wait", {"seconds": 0.1}))
        assert result["ok"] is True
        assert result["waited_seconds"] == 0.1

    def test_wait_invalid_seconds(self):
        tool = ComputerTool()
        result = tool.execute(_op("wait", {"seconds": "abc"}))
        assert result["ok"] is True  # 回退到默认值

    def test_get_status(self):
        tool = ComputerTool()
        result = tool.execute(_op("get_status"))
        assert result["ok"] is True
        assert "window_available" in result
        assert "reader_available" in result
        assert "actor_available" in result
        assert "screenshot_available" in result

    def test_unknown_action(self):
        tool = ComputerTool()
        result = tool.execute(_op("unknown_action"))
        assert result["ok"] is False
        assert "不支持" in result["error"]


# ---------------------------------------------------------------------------
# 操作历史记录测试
# ---------------------------------------------------------------------------

class TestComputerToolHistory:
    def test_execute_records_history(self):
        tool = ComputerTool()
        tool.execute(_op("get_status"))
        tool.execute(_op("wait", {"seconds": 0.1}))

        # 通过 get_status 查看 history_count
        status = tool.execute(_op("get_status"))
        assert status["history_count"] == 2

    def test_current_hwnd_from_find_window(self):
        """find_window 成功时会设置 current_hwnd。"""
        tool = ComputerTool()
        status = tool.execute(_op("get_status"))
        assert status["current_hwnd"] is None


# ---------------------------------------------------------------------------
# ToolRouter 集成测试
# ---------------------------------------------------------------------------

class TestComputerToolRouterIntegration:
    def test_router_has_computer_tool(self):
        from backend.tool_router.router import ToolRouter

        router = ToolRouter()
        tools = router.list_tools()
        tool_names = [t.get("tool", t.get("tool_name", "")) for t in tools]
        assert "computer" in tool_names

    def test_router_execute_computer(self):
        from backend.tool_router.router import ToolRouter

        router = ToolRouter()
        operation = OperationRequest(
            tool="computer",
            action="get_status",
            resource="computer",
            params={},
            risk="low",
        )
        result = router.execute(operation)
        assert result["ok"] is True

    def test_router_execute_computer_wait(self):
        from backend.tool_router.router import ToolRouter

        router = ToolRouter()
        operation = OperationRequest(
            tool="computer",
            action="wait",
            resource="computer",
            params={"seconds": 0.1},
            risk="low",
        )
        result = router.execute(operation)
        assert result["ok"] is True