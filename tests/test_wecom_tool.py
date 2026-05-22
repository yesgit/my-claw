"""WeComTool 单元测试。

在非 Windows 平台上通过 mock 测试工具注册、describe、参数校验等逻辑。
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestWeComToolDescribe(unittest.TestCase):
    """测试 WeComTool.describe() 输出。"""

    def test_describe_structure(self):
        """describe 返回标准结构。"""
        from backend.tools.wecom.tool import WeComTool

        tool = WeComTool()
        desc = tool.describe()

        self.assertEqual(desc["tool"], "wecom")
        self.assertEqual(desc["type"], "local")
        self.assertIn("actions", desc)
        self.assertIn("input_schema", desc)

    def test_describe_actions(self):
        """describe 包含 4 个 action。"""
        from backend.tools.wecom.tool import WeComTool

        tool = WeComTool()
        desc = tool.describe()

        action_names = {a["name"] for a in desc["actions"]}
        self.assertEqual(action_names, {"read_messages", "send_message", "list_recent_chats", "screenshot_chat"})

    def test_describe_risk_levels(self):
        """send_message 是 high risk。"""
        from backend.tools.wecom.tool import WeComTool

        tool = WeComTool()
        desc = tool.describe()

        risks = {a["name"]: a["default_risk"] for a in desc["actions"]}
        self.assertEqual(risks["send_message"], "high")
        self.assertEqual(risks["read_messages"], "medium")
        self.assertEqual(risks["list_recent_chats"], "low")
        self.assertEqual(risks["screenshot_chat"], "low")


class TestWeComToolExecuteValidation(unittest.TestCase):
    """测试 WeComTool.execute() 参数校验（不真正调用 Windows API）。"""

    def _make_tool_with_mock_reader(self):
        """创建一个 WeComTool 并 mock _get_reader 和倒计时。"""
        from backend.tools.wecom.tool import WeComTool

        tool = WeComTool()
        mock_reader = MagicMock()
        mock_reader.hwnd = None
        mock_reader.connect.return_value = False
        tool._get_reader = MagicMock(return_value=mock_reader)
        # 跳过倒计时等待，避免测试变慢
        tool._countdown_before_gui = MagicMock()
        return tool, mock_reader

    def test_unsupported_action(self):
        """不支持的 action 抛异常。"""
        from backend.models import OperationRequest
        from backend.tools.wecom.tool import WeComTool

        tool = WeComTool()
        op = OperationRequest(tool="wecom", action="bad_action", resource="", params={})
        with self.assertRaises(ValueError) as ctx:
            tool.execute(op)
        self.assertIn("bad_action", str(ctx.exception))

    def test_read_messages_missing_chat_name(self):
        """read_messages 缺少 chat_name 返回错误。"""
        from backend.models import OperationRequest
        from backend.tools.wecom.tool import WeComTool

        tool, _ = self._make_tool_with_mock_reader()
        op = OperationRequest(tool="wecom", action="read_messages", resource="", params={})
        result = tool.execute(op)
        self.assertFalse(result["ok"])
        self.assertIn("chat_name", result["error"])

    def test_send_message_missing_content(self):
        """send_message 缺少 content 返回错误。"""
        from backend.models import OperationRequest
        from backend.tools.wecom.tool import WeComTool

        tool, _ = self._make_tool_with_mock_reader()
        op = OperationRequest(
            tool="wecom", action="send_message",
            resource="测试群聊", params={"chat_name": "测试群聊"},
        )
        result = tool.execute(op)
        self.assertFalse(result["ok"])
        self.assertIn("content", result["error"])

    def test_send_message_missing_chat_name(self):
        """send_message 缺少 chat_name 返回错误。"""
        from backend.models import OperationRequest
        from backend.tools.wecom.tool import WeComTool

        tool, _ = self._make_tool_with_mock_reader()
        op = OperationRequest(
            tool="wecom", action="send_message",
            resource="", params={"content": "hello"},
        )
        result = tool.execute(op)
        self.assertFalse(result["ok"])
        self.assertIn("chat_name", result["error"])

    def test_connect_failure(self):
        """连接失败时返回错误。"""
        from backend.models import OperationRequest
        from backend.tools.wecom.tool import WeComTool

        tool, mock_reader = self._make_tool_with_mock_reader()
        mock_reader.hwnd = None
        mock_reader.connect.return_value = False

        op = OperationRequest(
            tool="wecom", action="send_message",
            resource="test", params={"chat_name": "test", "content": "hello"},
        )
        result = tool.execute(op)
        self.assertFalse(result["ok"])
        self.assertIn("企业微信", result["error"])

    def test_chat_name_from_resource(self):
        """chat_name 可以从 resource 字段取。"""
        from backend.models import OperationRequest
        from backend.tools.wecom.tool import WeComTool

        tool, mock_reader = self._make_tool_with_mock_reader()
        op = OperationRequest(
            tool="wecom", action="screenshot_chat",
            resource="我的群聊", params={},
        )
        # connect 失败，但能验证参数解析
        result = tool.execute(op)
        # 确认走到了 connect 失败而非参数缺失
        self.assertFalse(result["ok"])
        self.assertIn("企业微信", result["error"])


class TestVisionParsing(unittest.TestCase):
    """测试 vision.py 的 JSON 解析逻辑。"""

    def test_parse_messages_from_json_block(self):
        """从 markdown 代码块中解析消息。"""
        from backend.tools.wecom.vision import parse_messages_from_vision

        text = '''一些文字
```json
{"messages": [{"time": "10:00", "sender": "张三", "content": "你好"}]}
```
更多文字'''
        msgs = parse_messages_from_vision(text)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["sender"], "张三")

    def test_parse_messages_from_plain_json(self):
        """从纯 JSON 解析。"""
        from backend.tools.wecom.vision import parse_messages_from_vision

        text = '{"messages": [{"time": "10:00", "sender": "李四", "content": "测试"}]}'
        msgs = parse_messages_from_vision(text)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["sender"], "李四")

    def test_parse_messages_from_embedded_json(self):
        """从嵌入的 JSON 解析（宽松匹配）。"""
        from backend.tools.wecom.vision import parse_messages_from_vision

        text = '结果如下：{"messages": [{"time": "10:00", "sender": "王五", "content": "OK"}]} 完成'
        msgs = parse_messages_from_vision(text)
        self.assertEqual(len(msgs), 1)

    def test_parse_messages_empty(self):
        """无法解析时返回空列表。"""
        from backend.tools.wecom.vision import parse_messages_from_vision

        msgs = parse_messages_from_vision("这不是JSON")
        self.assertEqual(msgs, [])


class TestVisionChatParsing(unittest.TestCase):
    """测试 parse_chats_from_vision 解析聊天列表。"""

    def test_parse_chats_from_json_block(self):
        """从 markdown 代码块中解析聊天列表。"""
        from backend.tools.wecom.vision import parse_chats_from_vision

        text = '结果：\n```json\n{"chats": [{"name": "群A", "summary": "hello", "unread": 2}]}\n```'
        chats = parse_chats_from_vision(text)
        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0]["name"], "群A")

    def test_parse_chats_empty(self):
        """无法解析时返回空列表。"""
        from backend.tools.wecom.vision import parse_chats_from_vision

        chats = parse_chats_from_vision("无 JSON")
        self.assertEqual(chats, [])


class TestPlatformDispatch(unittest.TestCase):
    """测试 WeComTool 根据平台选择 Reader。"""

    def test_macos_dispatch(self):
        """macOS 上 _get_reader 返回 MacWeComReader。"""
        import platform
        from unittest.mock import patch

        if platform.system() != "Darwin":
            self.skipTest("仅在 macOS 上运行")

        from backend.tools.wecom.tool import WeComTool

        tool = WeComTool()
        reader = tool._get_reader()
        from backend.tools.wecom.macos.reader import MacWeComReader
        self.assertIsInstance(reader, MacWeComReader)

    def test_reader_has_hwnd_property(self):
        """MacWeComReader 有 hwnd 属性（兼容接口）。"""
        import platform
        if platform.system() != "Darwin":
            self.skipTest("仅在 macOS 上运行")

        from backend.tools.wecom.macos.reader import MacWeComReader
        reader = MacWeComReader()
        # 未连接时 hwnd 为 None
        self.assertIsNone(reader.hwnd)

    def test_reader_has_same_interface(self):
        """MacWeComReader 与 WeComReader 接口一致。"""
        import platform
        if platform.system() != "Darwin":
            self.skipTest("仅在 macOS 上运行")

        from backend.tools.wecom.macos.reader import MacWeComReader
        reader = MacWeComReader()

        # 验证关键方法存在
        for method_name in ("connect", "activate", "search_and_open_chat",
                            "scroll_to_latest", "send_message", "screenshot_window"):
            self.assertTrue(hasattr(reader, method_name), f"缺少方法: {method_name}")

        # 验证 hwnd 属性
        self.assertTrue(hasattr(reader, "hwnd"))


class TestChatNameActionGuard(unittest.TestCase):
    """测试 chat_name 为 action 名称时的防御性校验。"""

    def _make_tool(self):
        """创建一个 WeComTool 并 mock _get_reader 和倒计时。"""
        from backend.tools.wecom.tool import WeComTool

        tool = WeComTool()
        mock_reader = MagicMock()
        mock_reader.hwnd = None
        mock_reader.connect.return_value = False
        tool._get_reader = MagicMock(return_value=mock_reader)
        tool._countdown_before_gui = MagicMock()
        return tool

    def test_read_messages_rejects_action_name_as_chat_name(self):
        """read_messages: chat_name='read_messages' 应被拒绝。"""
        from backend.models import OperationRequest

        tool = self._make_tool()
        op = OperationRequest(
            tool="wecom", action="read_messages",
            resource="read_messages", params={},
        )
        result = tool.execute(op)
        self.assertFalse(result["ok"])
        self.assertIn("action 名称", result["error"])

    def test_send_message_rejects_action_name_as_chat_name(self):
        """send_message: chat_name='send_message' 应被拒绝。"""
        from backend.models import OperationRequest

        tool = self._make_tool()
        op = OperationRequest(
            tool="wecom", action="send_message",
            resource="send_message", params={"content": "hello"},
        )
        result = tool.execute(op)
        self.assertFalse(result["ok"])
        self.assertIn("action 名称", result["error"])

    def test_screenshot_chat_rejects_action_name_as_chat_name(self):
        """screenshot_chat: chat_name='screenshot_chat' 应被拒绝。"""
        from backend.models import OperationRequest

        tool = self._make_tool()
        op = OperationRequest(
            tool="wecom", action="screenshot_chat",
            resource="screenshot_chat", params={},
        )
        result = tool.execute(op)
        self.assertFalse(result["ok"])
        self.assertIn("action 名称", result["error"])

    def test_valid_chat_name_passes_guard(self):
        """正常群聊名不应被误拦截。"""
        from backend.models import OperationRequest

        tool = self._make_tool()
        op = OperationRequest(
            tool="wecom", action="read_messages",
            resource="我的工作群", params={},
        )
        result = tool.execute(op)
        # 应该走到 connect 失败，而非参数校验失败
        self.assertFalse(result["ok"])
        self.assertIn("企业微信", result["error"])


class TestToolRouterRegistration(unittest.TestCase):
    """测试 ToolRouter 注册了 wecom 工具。"""

    def test_wecom_in_tool_list(self):
        """list_tools 包含 wecom。"""
        from backend.tool_router.router import ToolRouter

        router = ToolRouter()
        tools = router.list_tools()
        tool_names = [t["tool"] for t in tools]
        self.assertIn("wecom", tool_names)

    def test_wecom_execute_dispatches(self):
        """execute 能分发到 wecom 工具。"""
        from backend.models import OperationRequest
        from backend.tool_router.router import ToolRouter

        router = ToolRouter()
        # mock wecom tool 的 execute
        original_execute = router._wecom.execute
        mock_result = {"ok": True, "tool": "wecom", "action": "test"}
        router._wecom.execute = MagicMock(return_value=mock_result)

        op = OperationRequest(tool="wecom", action="read_messages", resource="test", params={"chat_name": "test"})
        result = router.execute(op)
        self.assertEqual(result, mock_result)

        router._wecom.execute = original_execute  # restore


class TestCountdownBeforeGUI(unittest.TestCase):
    """测试 WeComTool 倒计时机制。"""

    def test_countdown_emits_events(self):
        """倒计时通过 event_callback 发送事件。"""
        from backend.tools.wecom.tool import WeComTool

        events: list[dict] = []
        tool = WeComTool(event_callback=lambda e: events.append(e))
        # 设置倒计时为 1 秒加速测试
        tool.GUI_COUNTDOWN_SECONDS = 1

        # 倒计时现在由 countdown_notify 模块处理，需要 patch 那里的 sleep
        with patch("backend.tools.computer.countdown_notify.time.sleep"):
            tool._countdown_before_gui("send_message", detail="测试群")

        # 事件：countdown_start + countdown ×1 + wecom_countdown_done
        start_events = [e for e in events if e["type"] == "countdown_start"]
        self.assertEqual(len(start_events), 1)
        self.assertEqual(start_events[0]["seconds"], 1)
        self.assertEqual(start_events[0]["tool"], "wecom")

        countdown_events = [e for e in events if e["type"] == "countdown"]
        self.assertEqual(len(countdown_events), 1)
        self.assertEqual(countdown_events[0]["remaining_seconds"], 1)
        self.assertEqual(countdown_events[0]["tool"], "wecom")

        done_events = [e for e in events if e["type"] == "wecom_countdown_done"]
        self.assertEqual(len(done_events), 1)

    def test_countdown_skipped_for_no_gui_actions(self):
        """list_recent_chats 不触发倒计时。"""
        from backend.models import OperationRequest
        from backend.tools.wecom.tool import WeComTool

        events: list[dict] = []
        tool = WeComTool(event_callback=lambda e: events.append(e))
        tool._get_reader = MagicMock(return_value=MagicMock(hwnd=None, connect=MagicMock(return_value=False)))

        op = OperationRequest(tool="wecom", action="list_recent_chats", resource="", params={})
        tool.execute(op)

        # 不应有任何倒计时事件（只有 connect 失败的结果）
        countdown_events = [e for e in events if "countdown" in e.get("type", "")]
        self.assertEqual(len(countdown_events), 0)

    def test_countdown_triggered_for_send_message(self):
        """send_message 触发倒计时（mock 掉 time.sleep）。"""
        from backend.models import OperationRequest
        from backend.tools.wecom.tool import WeComTool

        events: list[dict] = []
        tool = WeComTool(event_callback=lambda e: events.append(e))
        mock_reader = MagicMock()
        mock_reader.hwnd = None
        mock_reader.connect.return_value = False
        tool._get_reader = MagicMock(return_value=mock_reader)

        with patch("backend.tools.computer.countdown_notify.time.sleep"):
            op = OperationRequest(
                tool="wecom", action="send_message",
                resource="测试群", params={"content": "hi"},
            )
            tool.execute(op)

        countdown_events = [e for e in events if e.get("type") == "countdown"]
        done_events = [e for e in events if e.get("type") == "wecom_countdown_done"]
        self.assertEqual(len(countdown_events), tool.GUI_COUNTDOWN_SECONDS)
        self.assertEqual(len(done_events), 1)

    def test_no_callback_no_error(self):
        """没有 event_callback 时倒计时不会报错。"""
        from backend.tools.wecom.tool import WeComTool

        tool = WeComTool()  # 无 callback
        tool.GUI_COUNTDOWN_SECONDS = 1
        with patch("backend.tools.computer.countdown_notify.time.sleep"):
            # 应不抛异常
            tool._countdown_before_gui("read_messages")

    def test_gui_done_event_on_success(self):
        """执行成功后发送 wecom_gui_done 事件。"""
        from backend.models import OperationRequest
        from backend.tools.wecom.tool import WeComTool

        events: list[dict] = []
        tool = WeComTool(event_callback=lambda e: events.append(e))
        tool._read_messages = MagicMock(return_value={"ok": True, "messages": []})

        with patch("backend.tools.computer.countdown_notify.time.sleep"):
            op = OperationRequest(
                tool="wecom", action="read_messages",
                resource="测试群", params={"chat_name": "测试群"},
            )
            result = tool.execute(op)

        self.assertTrue(result["ok"])
        gui_done = [e for e in events if e.get("type") == "wecom_gui_done"]
        self.assertEqual(len(gui_done), 1)
        self.assertTrue(gui_done[0]["ok"])

    def test_gui_done_event_on_connect_failure(self):
        """连接失败时也发送 wecom_gui_done 事件（ok=False）。"""
        from backend.models import OperationRequest
        from backend.tools.wecom.tool import WeComTool

        events: list[dict] = []
        tool = WeComTool(event_callback=lambda e: events.append(e))
        mock_reader = MagicMock()
        mock_reader.hwnd = None
        mock_reader.connect.return_value = False
        tool._get_reader = MagicMock(return_value=mock_reader)

        with patch("backend.tools.computer.countdown_notify.time.sleep"):
            op = OperationRequest(
                tool="wecom", action="send_message",
                resource="测试群", params={"chat_name": "测试群", "content": "hi"},
            )
            result = tool.execute(op)

        self.assertFalse(result["ok"])
        gui_done = [e for e in events if e.get("type") == "wecom_gui_done"]
        self.assertEqual(len(gui_done), 1)
        self.assertFalse(gui_done[0]["ok"])


if __name__ == "__main__":
    unittest.main()
