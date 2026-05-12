from __future__ import annotations

import unittest

from backend.agent.react_agent import ReactAgent
from backend.models import OperationRequest


class FakeLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.index = 0

    def chat(self, messages, temperature: float = 0.0) -> str:
        if self.index >= len(self.responses):
            return '{"type":"final","final_answer":"done"}'
        value = self.responses[self.index]
        self.index += 1
        return value


class FakeGuard:
    def approve(self, operation: OperationRequest) -> bool:
        return True


class FakeRouter:
    def execute(self, operation: OperationRequest):
        return {"ok": True}


class TestReactAgentParseOperation(unittest.TestCase):
    """测试 ReactAgent 的 _parse_operation 方法（原 SimplePlanner/LLMPlanner 的 JSON 解析逻辑）"""

    def setUp(self) -> None:
        llm = FakeLLMClient(['{"type":"final","final_answer":"ok"}'])
        self.agent = ReactAgent(client=llm, guard=FakeGuard(), router=FakeRouter())

    def test_parse_valid_operation(self) -> None:
        op = self.agent._parse_operation(
            {"tool": "filesystem", "action": "write_file", "resource": "/tmp/a.txt", "params": {"content": "x"}, "risk": "medium"}
        )
        self.assertEqual(op.tool, "filesystem")
        self.assertEqual(op.action, "write_file")
        self.assertEqual(op.resource, "/tmp/a.txt")
        self.assertEqual(op.params, {"content": "x"})
        self.assertEqual(op.risk, "medium")

    def test_parse_minimal_operation(self) -> None:
        op = self.agent._parse_operation(
            {"tool": "filesystem", "action": "list_dir", "resource": "/tmp"}
        )
        self.assertEqual(op.action, "list_dir")
        self.assertEqual(op.resource, "/tmp")
        self.assertEqual(op.params, {})
        self.assertEqual(op.risk, "medium")

    def test_rejects_extra_keys(self) -> None:
        with self.assertRaises(ValueError):
            self.agent._parse_operation(
                {"tool": "filesystem", "action": "write_file", "resource": "/tmp/a.txt", "extra": 1}
            )

    def test_rejects_invalid_tool(self) -> None:
        with self.assertRaises(ValueError):
            self.agent._parse_operation(
                {"tool": "docker", "action": "run", "resource": "/tmp/a.txt"}
            )

    def test_rejects_invalid_risk(self) -> None:
        with self.assertRaises(ValueError):
            self.agent._parse_operation(
                {"tool": "filesystem", "action": "write_file", "resource": "/tmp/a.txt", "risk": "critical"}
            )

    def test_rejects_non_object_params(self) -> None:
        with self.assertRaises(ValueError):
            self.agent._parse_operation(
                {"tool": "filesystem", "action": "write_file", "resource": "/tmp/a.txt", "params": []}
            )

    def test_mcp_resource_must_match_scheme(self) -> None:
        with self.assertRaises(ValueError):
            self.agent._parse_operation(
                {"tool": "mcp", "action": "read_file", "resource": "/tmp/a.txt"}
            )

    def test_mcp_resource_valid(self) -> None:
        op = self.agent._parse_operation(
            {"tool": "mcp", "action": "call_tool", "resource": "mcp://server/tool"}
        )
        self.assertEqual(op.tool, "mcp")
        self.assertEqual(op.resource, "mcp://server/tool")

    def test_missing_required_keys(self) -> None:
        with self.assertRaises(ValueError):
            self.agent._parse_operation({"tool": "filesystem"})


if __name__ == "__main__":
    unittest.main()
