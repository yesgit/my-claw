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


class TestReactAgentParseJson(unittest.TestCase):
    """测试 ReactAgent 的 _parse_json 和 _parse_decision 方法（原 LLMPlanner 的 JSON 提取逻辑）"""

    def setUp(self) -> None:
        llm = FakeLLMClient(['{"type":"final","final_answer":"ok"}'])
        self.agent = ReactAgent(client=llm, guard=FakeGuard(), router=FakeRouter())

    def test_parse_raw_json(self) -> None:
        decision = self.agent._parse_decision(
            '{"type":"action","operation":{"tool":"filesystem","action":"write_file","resource":"/tmp/a.txt","params":{"content":"hello"},"risk":"medium"}}'
        )
        self.assertEqual(decision["type"], "action")
        self.assertEqual(len(decision["operations"]), 1)
        op = decision["operations"][0]["operation"]
        self.assertEqual(op.tool, "filesystem")
        self.assertEqual(op.action, "write_file")
        self.assertEqual(op.resource, "/tmp/a.txt")
        self.assertEqual(op.params["content"], "hello")

    def test_parse_fenced_json(self) -> None:
        decision = self.agent._parse_decision(
            "前言\n```json\n{\"type\":\"action\",\"operation\":{\"tool\":\"filesystem\",\"action\":\"list_dir\",\"resource\":\"/tmp\",\"params\":{},\"risk\":\"medium\"}}\n```"
        )
        self.assertEqual(decision["type"], "action")
        op = decision["operations"][0]["operation"]
        self.assertEqual(op.action, "list_dir")
        self.assertEqual(op.resource, "/tmp")

    def test_missing_json_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.agent._parse_decision("没有 JSON")

    def test_rejects_extra_keys_in_operation(self) -> None:
        with self.assertRaises(ValueError):
            self.agent._parse_decision(
                '{"type":"action","operation":{"tool":"filesystem","action":"write_file","resource":"/tmp/a.txt","params":{},"risk":"medium","extra":1}}'
            )

    def test_rejects_invalid_tool_and_risk(self) -> None:
        with self.assertRaises(ValueError):
            self.agent._parse_decision(
                '{"type":"action","operation":{"tool":"docker","action":"run","resource":"/tmp/a.txt","params":{},"risk":"critical"}}'
            )

    def test_rejects_non_object_params(self) -> None:
        with self.assertRaises(ValueError):
            self.agent._parse_decision(
                '{"type":"action","operation":{"tool":"filesystem","action":"write_file","resource":"/tmp/a.txt","params":[],"risk":"medium"}}'
            )

    def test_mcp_resource_must_match_scheme(self) -> None:
        with self.assertRaises(ValueError):
            self.agent._parse_decision(
                '{"type":"action","operation":{"tool":"mcp","action":"read_file","resource":"/tmp/a.txt","params":{},"risk":"medium"}}'
            )

    def test_parse_final_decision(self) -> None:
        decision = self.agent._parse_decision(
            '{"type":"final","final_answer":"任务完成"}'
        )
        self.assertEqual(decision["type"], "final")
        self.assertEqual(decision["final_answer"], "任务完成")


if __name__ == "__main__":
    unittest.main()
