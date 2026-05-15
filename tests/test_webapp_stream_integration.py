from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.memory.conversation_store import ConversationStore
from backend.memory.rule_store import RuleStore
from backend import webapp


class TestWebappStreamIntegration(unittest.TestCase):
    def test_create_schedule_reuses_owner_session_as_runtime(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            conversation_db = root / "conversations.db"

            def conversation_store_factory() -> ConversationStore:
                return ConversationStore(db_path=conversation_db)

            with patch("backend.webapp.ConversationStore", new=conversation_store_factory):
                session_result = webapp.create_session(
                    webapp.CreateSessionRequest(
                        name="定时任务源会话",
                        config=webapp.SessionConfigPayload(
                            providerId="openai-local",
                            modelId="gpt-4.1-mini",
                            maxSteps=8,
                        ),
                    )
                )
                self.assertTrue(session_result["ok"])
                session_id = session_result["session"]["id"]

                schedule_result = webapp.create_session_schedule(
                    session_id=session_id,
                    payload=webapp.ScheduledTaskCreateRequest(
                        name="每5分钟写诗",
                        prompt="请写一首优美的诗歌。",
                        intervalSeconds=300,
                        enabled=True,
                    ),
                )
                schedule = schedule_result["schedule"]
                self.assertEqual(schedule["session_id"], session_id)
                self.assertEqual(schedule["runtime_session_id"], session_id)

                sessions = conversation_store_factory().list_sessions(limit=50, include_runtime=True)
                runtime_sessions = [
                    item for item in sessions if item.get("session_type") == "schedule-runtime"
                ]
                self.assertEqual(runtime_sessions, [])

    def test_stream_run_persists_conversation_and_can_query(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            target_dir = root / "workspace"
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "hello.txt").write_text("hello", encoding="utf-8")

            conversation_db = root / "conversations.db"
            rule_db = root / "rules.db"

            def conversation_store_factory() -> ConversationStore:
                return ConversationStore(db_path=conversation_db)

            def rule_store_factory() -> RuleStore:
                return RuleStore(db_path=rule_db)

            class FakeOpenAIClient:
                def __init__(self, config) -> None:  # noqa: ANN001
                    self._calls = 0

                def chat(self, messages, temperature: float = 0.0) -> str:  # noqa: ANN001
                    if self._calls == 0:
                        self._calls += 1
                        return json.dumps(
                            {
                                "type": "action",
                                "operation": {
                                    "tool": "filesystem",
                                    "action": "list_dir",
                                    "resource": str(target_dir),
                                    "params": {},
                                    "risk": "medium",
                                },
                            },
                            ensure_ascii=False,
                        )

                    return json.dumps(
                        {
                            "type": "final",
                            "final_answer": "流式执行完成",
                        },
                        ensure_ascii=False,
                    )

            with patch("backend.webapp.ConversationStore", new=conversation_store_factory), patch(
                "backend.webapp.RuleStore", new=rule_store_factory
            ), patch("backend.webapp.OpenAICompatibleChatClient", new=FakeOpenAIClient):
                client = TestClient(webapp.app)

                run_payload = {
                    "goal": "请列出目录并结束",
                    "llmBaseUrl": "http://fake-llm/v1",
                    "llmApiKey": "fake-key",
                    "llmModel": "fake-model",
                    "maxSteps": 4,
                    "approvalDecision": "1",
                    "filesystemAllowedDirs": [str(target_dir)],
                }
                stream_resp = client.post("/api/run-react-stream", json=run_payload)

                self.assertEqual(stream_resp.status_code, 200)
                events = [json.loads(line) for line in stream_resp.text.splitlines() if line.strip()]
                self.assertTrue(any(event.get("type") == "run_boot" for event in events))
                self.assertTrue(any(event.get("type") == "step_complete" for event in events))
                self.assertTrue(
                    any(
                        event.get("type") == "run_complete" and event.get("status") == "completed"
                        for event in events
                    )
                )

                list_resp = client.get("/api/conversations")
                self.assertEqual(list_resp.status_code, 200)
                payload = list_resp.json()
                self.assertTrue(payload["ok"])
                self.assertGreaterEqual(payload["count"], 1)

                latest = payload["conversations"][0]
                self.assertEqual(latest["goal"], "请列出目录并结束")
                self.assertEqual(latest["status"], "completed")
                self.assertEqual(latest["final_answer"], "流式执行完成")

                get_resp = client.get(f"/api/conversations/{latest['id']}")
                self.assertEqual(get_resp.status_code, 200)
                one = get_resp.json()["conversation"]
                self.assertEqual(one["id"], latest["id"])

    def test_stream_reject_dangerous_action_keeps_file_and_persists(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            target_file = root / "danger.txt"
            target_file.write_text("keep me", encoding="utf-8")

            conversation_db = root / "conversations.db"
            rule_db = root / "rules.db"

            def conversation_store_factory() -> ConversationStore:
                return ConversationStore(db_path=conversation_db)

            def rule_store_factory() -> RuleStore:
                return RuleStore(db_path=rule_db)

            class FakeOpenAIClient:
                def __init__(self, config) -> None:  # noqa: ANN001
                    self._calls = 0

                def chat(self, messages, temperature: float = 0.0) -> str:  # noqa: ANN001
                    if self._calls == 0:
                        self._calls += 1
                        return json.dumps(
                            {
                                "type": "action",
                                "operation": {
                                    "tool": "filesystem",
                                    "action": "delete_path",
                                    "resource": str(target_file),
                                    "params": {},
                                    "risk": "high",
                                },
                            },
                            ensure_ascii=False,
                        )

                    return json.dumps(
                        {
                            "type": "final",
                            "final_answer": "已停止危险操作",
                        },
                        ensure_ascii=False,
                    )

            with patch("backend.webapp.ConversationStore", new=conversation_store_factory), patch(
                "backend.webapp.RuleStore", new=rule_store_factory
            ), patch("backend.webapp.OpenAICompatibleChatClient", new=FakeOpenAIClient):
                client = TestClient(webapp.app)

                run_payload = {
                    "goal": "删除危险文件",
                    "llmBaseUrl": "http://fake-llm/v1",
                    "llmApiKey": "fake-key",
                    "llmModel": "fake-model",
                    "maxSteps": 4,
                    "approvalDecision": "n",
                    "filesystemAllowedDirs": [str(root)],
                }
                stream_resp = client.post("/api/run-react-stream", json=run_payload)

                self.assertEqual(stream_resp.status_code, 200)
                events = [json.loads(line) for line in stream_resp.text.splitlines() if line.strip()]
                self.assertTrue(
                    any(
                        event.get("type") == "approval" and event.get("approved") is False
                        for event in events
                    )
                )
                self.assertTrue(
                    any(
                        event.get("type") == "run_complete" and event.get("final_answer") == "已停止危险操作"
                        for event in events
                    )
                )

                self.assertTrue(target_file.exists())
                self.assertEqual(target_file.read_text(encoding="utf-8"), "keep me")

                list_resp = client.get("/api/conversations")
                self.assertEqual(list_resp.status_code, 200)
                payload = list_resp.json()
                self.assertTrue(payload["ok"])
                self.assertGreaterEqual(payload["count"], 1)

                latest = payload["conversations"][0]
                self.assertEqual(latest["goal"], "删除危险文件")
                self.assertEqual(latest["status"], "completed")
                self.assertEqual(latest["final_answer"], "已停止危险操作")


if __name__ == "__main__":
    unittest.main()
