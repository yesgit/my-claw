from __future__ import annotations

import unittest

from backend.planner.llm_planner import LLMPlanner


class FakeLLMClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.0) -> str:
        self.calls.append(messages)
        return self.content


class TestLLMPlanner(unittest.TestCase):
    def test_parse_raw_json(self) -> None:
        client = FakeLLMClient(
            '{"tool":"filesystem","action":"write_file","resource":"/tmp/a.txt","params":{"content":"hello"},"risk":"medium"}'
        )
        planner = LLMPlanner(client=client, model_name="demo")

        op = planner.plan("写一个文件")

        self.assertEqual(op.tool, "filesystem")
        self.assertEqual(op.action, "write_file")
        self.assertEqual(op.resource, "/tmp/a.txt")
        self.assertEqual(op.params["content"], "hello")
        self.assertEqual(len(client.calls), 1)

    def test_parse_fenced_json(self) -> None:
        client = FakeLLMClient(
            "前言\n```json\n{\"tool\":\"filesystem\",\"action\":\"list_dir\",\"resource\":\"/tmp\",\"params\":{},\"risk\":\"medium\"}\n```"
        )
        planner = LLMPlanner(client=client, model_name="demo")

        op = planner.plan("列出目录")

        self.assertEqual(op.action, "list_dir")
        self.assertEqual(op.resource, "/tmp")

    def test_missing_json_raises(self) -> None:
        client = FakeLLMClient("没有 JSON")
        planner = LLMPlanner(client=client, model_name="demo")

        with self.assertRaises(ValueError):
            planner.plan("bad output")

    def test_rejects_extra_keys(self) -> None:
        client = FakeLLMClient(
            '{"tool":"filesystem","action":"write_file","resource":"/tmp/a.txt","params":{},"risk":"medium","extra":1}'
        )
        planner = LLMPlanner(client=client, model_name="demo")

        with self.assertRaises(ValueError):
            planner.plan("bad output")

    def test_rejects_invalid_tool_and_risk(self) -> None:
        client = FakeLLMClient(
            '{"tool":"shell","action":"run","resource":"/tmp/a.txt","params":{},"risk":"critical"}'
        )
        planner = LLMPlanner(client=client, model_name="demo")

        with self.assertRaises(ValueError):
            planner.plan("bad output")

    def test_rejects_non_object_params(self) -> None:
        client = FakeLLMClient(
            '{"tool":"filesystem","action":"write_file","resource":"/tmp/a.txt","params":[],"risk":"medium"}'
        )
        planner = LLMPlanner(client=client, model_name="demo")

        with self.assertRaises(ValueError):
            planner.plan("bad output")

    def test_mcp_resource_must_match_scheme(self) -> None:
        client = FakeLLMClient(
            '{"tool":"mcp","action":"read_file","resource":"/tmp/a.txt","params":{},"risk":"medium"}'
        )
        planner = LLMPlanner(client=client, model_name="demo")

        with self.assertRaises(ValueError):
            planner.plan("bad output")


if __name__ == "__main__":
    unittest.main()
