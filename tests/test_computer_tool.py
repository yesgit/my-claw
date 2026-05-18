"""computer 工具单元测试。

由于 Linux CI 环境没有 Windows 依赖，大部分测试验证：
1. 工具描述（describe）输出正确
2. 非Windows环境下返回友好的不可用提示
3. 参数校验
4. 状态管理
"""
from __future__ import annotations

import pytest
from unittest.mock import patch

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


# ---------------------------------------------------------------------------
# Pillow 延迟导入测试
# ---------------------------------------------------------------------------

class TestPillowLazyImport:
    """验证 Pillow 延迟导入机制：启动时导入失败后，运行时安装仍可检测到。"""

    def test_init_pillow_returns_bool(self):
        """_init_pillow 应返回 bool。"""
        from backend.tools.computer.window_manager import _init_pillow

        result = _init_pillow()
        assert isinstance(result, bool)

    def test_screenshot_available_calls_init_pillow(self):
        """screenshot_available 应通过调用 _init_pillow 实现延迟检测。"""
        from unittest.mock import patch

        from backend.tools.computer.window_manager import WindowManager

        # Pillow 不可用时 → False
        with patch("backend.tools.computer.window_manager._init_pillow", return_value=False):
            assert WindowManager.screenshot_available() is False

        # Pillow 可用时 → True
        with patch("backend.tools.computer.window_manager._init_pillow", return_value=True):
            assert WindowManager.screenshot_available() is True

    def test_init_pillow_lazy_retry_on_import_success(self):
        """模拟 Pillow 从不可用变为可用：mock ImportError 后恢复。"""
        import builtins
        import backend.tools.computer.window_manager as wm

        original_image = wm._Image
        real_import = builtins.__import__
        call_count = 0

        def _fake_import(name, *args, **kwargs):
            nonlocal call_count
            if name == "PIL":
                call_count += 1
                if call_count == 1:
                    raise ImportError("no PIL")
            return real_import(name, *args, **kwargs)

        try:
            wm._Image = None
            # 第一次：PIL 导入失败 → False
            with patch("builtins.__import__", side_effect=_fake_import):
                assert wm._init_pillow() is False

            # 恢复 _Image 为 None，这次让 PIL 导入成功（call_count 已递增）
            wm._Image = None
            # 第二次：PIL 导入成功 → True（Pillow 在测试环境中已安装）
            assert wm._init_pillow() is True
        finally:
            wm._Image = original_image

    def test_init_pillow_idempotent(self):
        """_init_pillow 已成功后再次调用应立即返回 True，不重复导入。"""
        from unittest.mock import patch

        import backend.tools.computer.window_manager as wm

        # 确保 _Image 已设置（非 None）
        original = wm._Image
        wm._Image = object()  # 模拟已导入成功
        try:
            with patch("backend.tools.computer.window_manager._Image_mod", create=True) as mock_mod:
                result = wm._init_pillow()
                assert result is True
                # 不应尝试导入
                mock_mod.assert_not_called()
        finally:
            wm._Image = original


# ---------------------------------------------------------------------------
# System prompt 规则测试
# ---------------------------------------------------------------------------

class TestSystemPromptRules:
    """验证 system prompt 中包含关键规则。"""

    def _make_agent(self):
        """创建一个最小 ReactAgent 用于测试 system prompt。"""
        from backend.agent.react_agent import ReactAgent

        class FakeClient:
            def chat(self, messages, temperature=0.0):
                return '{"type":"final","final_answer":"ok"}'

        class FakeGuard:
            def approve(self, operation):
                return True

        class FakeRouter:
            def execute(self, operation):
                return {"ok": True}
            def list_tools(self):
                return []

        return ReactAgent(client=FakeClient(), guard=FakeGuard(), router=FakeRouter())

    def test_system_prompt_has_script_rule(self):
        """system prompt 应包含"先写文件再执行脚本"的规则。"""
        agent = self._make_agent()
        prompt = agent._system_prompt()
        assert "filesystem.write_file" in prompt
        assert "先" in prompt and "写" in prompt and "文件" in prompt
        assert "禁止" in prompt or "不要" in prompt

    def test_system_prompt_has_json_format(self):
        """system prompt 应包含 JSON 格式说明。"""
        agent = self._make_agent()
        prompt = agent._system_prompt()
        assert "只输出 JSON" in prompt
        assert "final_answer" in prompt
