"""WeComTool 单元测试。

在非 Windows 平台上通过 mock 测试工具注册、describe、参数校验等逻辑。
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock


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
        """创建一个 WeComTool 并 mock _get_reader。"""
        from backend.tools.wecom.tool import WeComTool

        tool = WeComTool()
        mock_reader = MagicMock()
        mock_reader.hwnd = None
        mock_reader.connect.return_value = False
        tool._get_reader = MagicMock(return_value=mock_reader)
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


if __name__ == "__main__":
    unittest.main()