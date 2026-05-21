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
    def test_emits_streaming_events(self) -> None:
        llm = FakeLLMClient(
            [
                '{"type":"action","operation":{"tool":"filesystem","action":"list_dir","resource":"/tmp","params":{},"risk":"medium"}}',
                '{"type":"final","final_answer":"任务完成"}',
            ]
        )
        events: list[dict] = []

        agent = ReactAgent(
            client=llm,
            guard=FakeGuard(allow=True),
            router=FakeRouter(),
            max_steps=5,
            event_callback=events.append,
        )

        result = agent.run("列出目录")

        self.assertEqual(result.status, "completed")
        self.assertTrue(any(event["type"] == "run_start" for event in events))
        self.assertTrue(any(event["type"] == "step_complete" for event in events))
        self.assertTrue(any(event["type"] == "run_complete" for event in events))

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
        """max_steps 作为安全兜底，LLM 持续输出 action 仍未结束时应触发"""
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

    def test_cannot_complete(self) -> None:
        """LLM 判断暂时无法完成任务时，输出 cannot_complete 主动结束"""
        llm = FakeLLMClient(
            [
                '{"type":"action","operation":{"tool":"filesystem","action":"read_file","resource":"/不存在.txt","params":{},"risk":"medium"}}',
                '{"type":"cannot_complete","reason":"文件 /不存在.txt 不存在，无法读取。"}',
            ]
        )
        guard = FakeGuard(allow=True)
        router = FakeRouter()
        agent = ReactAgent(client=llm, guard=guard, router=router, max_steps=10)

        result = agent.run("读取不存在的文件")

        self.assertEqual(result.status, "cannot_complete")
        self.assertEqual(result.final_answer, "文件 /不存在.txt 不存在，无法读取。")
        self.assertEqual(len(result.steps), 1)

    def test_cannot_complete_missing_reason(self) -> None:
        """cannot_complete 缺少 reason 时应解析失败，反馈给 LLM 重试"""
        llm = FakeLLMClient(
            [
                '{"type":"cannot_complete","reason":""}',
                '{"type":"final","final_answer":"已恢复"}',
            ]
        )
        agent = ReactAgent(client=llm, guard=FakeGuard(allow=True), router=FakeRouter(), max_steps=5)

        result = agent.run("测试空 reason")

        # 第一次解析失败（reason 为空），第二次输出 final，任务完成
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.final_answer, "已恢复")

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

    def test_function_call_wecom_read_messages(self) -> None:
        """wecom.read_messages function_call 应被正确解析并执行"""
        llm = FakeLLMClient(
            [
                '{"type":"action","function_call":{"id":"call_wecom_1","name":"wecom.read_messages","arguments":{"resource":"","params":{"chat_name":"张三"},"risk":"medium"}}}',
                '{"type":"final","final_answer":"已读取企业微信消息"}',
            ]
        )
        guard = FakeGuard(allow=True)
        router = FakeRouter()
        agent = ReactAgent(client=llm, guard=guard, router=router, max_steps=4)

        result = agent.run("读取企业微信消息")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.final_answer, "已读取企业微信消息")
        self.assertEqual(len(result.steps), 1)
        self.assertEqual(result.steps[0]["operation"]["tool"], "wecom")
        self.assertEqual(result.steps[0]["operation"]["action"], "read_messages")
        self.assertEqual(result.steps[0]["tool_call_id"], "call_wecom_1")

    def test_function_call_wecom_no_resource_auto_fills(self) -> None:
        """wecom 工具无 resource 时应自动填充为 action 名称"""
        llm = FakeLLMClient(
            [
                '{"type":"action","function_call":{"id":"call_wecom_2","name":"wecom.list_recent_chats","arguments":{"params":{},"risk":"low"}}}',
                '{"type":"final","final_answer":"已列出最近聊天"}',
            ]
        )
        guard = FakeGuard(allow=True)
        router = FakeRouter()
        agent = ReactAgent(client=llm, guard=guard, router=router, max_steps=4)

        result = agent.run("列出企业微信最近聊天")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.steps[0]["operation"]["resource"], "list_recent_chats")
        self.assertEqual(router.calls, 1)

    def test_function_call_invalid_name_triggers_parse_error(self) -> None:
        """无效的 function_call.name 会触发解析失败，反馈给 LLM 重试"""
        llm = FakeLLMClient(
            [
                '{"type":"action","function_call":{"name":"invalidname","arguments":{"resource":"/tmp/a.txt"}}}',
                '{"type":"final","final_answer":"已修复"}',
            ]
        )
        agent = ReactAgent(client=llm, guard=FakeGuard(allow=True), router=FakeRouter(), max_steps=3)

        result = agent.run("bad call")

        # 第一次解析失败，第二次输出 final
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.final_answer, "已修复")
        self.assertEqual(len(result.steps), 1)
        self.assertIn("error", result.steps[0])

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
