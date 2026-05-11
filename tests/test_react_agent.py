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
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.calls = 0

    def approve(self, operation: OperationRequest) -> bool:
        self.calls += 1
        return self.allow


class FakeRouter:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, operation: OperationRequest):
        self.calls += 1
        return {"ok": True, "echo_action": operation.action}


class TestReactAgent(unittest.TestCase):
    def test_action_then_final(self) -> None:
        llm = FakeLLMClient(
            [
                '{"type":"action","operation":{"tool":"filesystem","action":"list_dir","resource":"/tmp","params":{},"risk":"medium"}}',
                '{"type":"final","final_answer":"任务完成"}',
            ]
        )
        guard = FakeGuard(allow=True)
        router = FakeRouter()
        agent = ReactAgent(client=llm, guard=guard, router=router, max_steps=5)

        result = agent.run("列出目录")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.final_answer, "任务完成")
        self.assertEqual(len(result.steps), 1)
        self.assertEqual(router.calls, 1)
        self.assertEqual(guard.calls, 1)

    def test_policy_reject_then_final(self) -> None:
        llm = FakeLLMClient(
            [
                '{"type":"action","operation":{"tool":"filesystem","action":"delete_path","resource":"/tmp/a","params":{},"risk":"high"}}',
                '{"type":"final","final_answer":"已停止危险操作"}',
            ]
        )
        guard = FakeGuard(allow=False)
        router = FakeRouter()
        agent = ReactAgent(client=llm, guard=guard, router=router, max_steps=5)

        result = agent.run("删除文件")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.final_answer, "已停止危险操作")
        self.assertEqual(len(result.steps), 1)
        self.assertEqual(result.steps[0]["observation"]["error"], "rejected_by_policy_guard")
        self.assertEqual(router.calls, 0)

    def test_reaches_max_steps(self) -> None:
        llm = FakeLLMClient(
            [
                '{"type":"action","operation":{"tool":"filesystem","action":"list_dir","resource":"/tmp","params":{},"risk":"medium"}}',
                '{"type":"action","operation":{"tool":"filesystem","action":"list_dir","resource":"/tmp","params":{},"risk":"medium"}}',
            ]
        )
        agent = ReactAgent(client=llm, guard=FakeGuard(allow=True), router=FakeRouter(), max_steps=2)

        result = agent.run("循环")

        self.assertEqual(result.status, "max_steps_reached")
        self.assertEqual(len(result.steps), 2)

    def test_function_call_action_then_final(self) -> None:
        llm = FakeLLMClient(
            [
                '{"type":"action","function_call":{"id":"call_single","name":"filesystem.read_file","arguments":{"resource":"/tmp/a.txt","params":{},"risk":"medium"}}}',
                '{"type":"final","final_answer":"已读取"}',
            ]
        )
        guard = FakeGuard(allow=True)
        router = FakeRouter()
        agent = ReactAgent(client=llm, guard=guard, router=router, max_steps=4)

        result = agent.run("读取文件")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.final_answer, "已读取")
        self.assertEqual(len(result.steps), 1)
        self.assertEqual(result.steps[0]["operation"]["action"], "read_file")
        self.assertEqual(result.steps[0]["tool_call_id"], "call_single")
        self.assertEqual(result.steps[0]["observation"]["tool_call_id"], "call_single")

    def test_function_call_invalid_name_raises(self) -> None:
        llm = FakeLLMClient(
            ['{"type":"action","function_call":{"name":"invalidname","arguments":{"resource":"/tmp/a.txt"}}}']
        )
        agent = ReactAgent(client=llm, guard=FakeGuard(allow=True), router=FakeRouter(), max_steps=1)

        with self.assertRaises(ValueError):
            agent.run("bad call")

    def test_action_batch_executes_multiple_operations(self) -> None:
        llm = FakeLLMClient(
            [
                '{"type":"action_batch","function_calls":[{"id":"call_1","name":"filesystem.read_file","arguments":{"resource":"/tmp/a.txt","params":{},"risk":"medium"}},{"id":"call_2","name":"filesystem.list_dir","arguments":{"resource":"/tmp","params":{},"risk":"medium"}}]}',
                '{"type":"final","final_answer":"批量完成"}',
            ]
        )
        guard = FakeGuard(allow=True)
        router = FakeRouter()
        agent = ReactAgent(client=llm, guard=guard, router=router, max_steps=4)

        result = agent.run("批量执行")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.final_answer, "批量完成")
        self.assertEqual(len(result.steps), 1)
        self.assertIn("operations", result.steps[0])
        self.assertIn("observations", result.steps[0])
        self.assertEqual(len(result.steps[0]["operations"]), 2)
        self.assertEqual(result.steps[0]["tool_call_ids"], ["call_1", "call_2"])
        self.assertEqual(result.steps[0]["observations"][0]["tool_call_id"], "call_1")
        self.assertEqual(result.steps[0]["observations"][1]["tool_call_id"], "call_2")
        self.assertEqual(router.calls, 2)


if __name__ == "__main__":
    unittest.main()
