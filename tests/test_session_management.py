"""会话管理测试"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest

from backend.memory.conversation_store import ConversationStore


@pytest.fixture
def store() -> ConversationStore:
    """创建临时的存储对象"""
    return ConversationStore(db_path=":memory:")


class TestSessionManagement:
    """会话 CRUD 操作测试"""

    def test_create_session(self, store: ConversationStore) -> None:
        """测试创建会话"""
        session_id = store.create_session(
            name="Test Session",
            config={
                "providerId": "openai-local",
                "modelId": "gpt-4.1-mini",
                "maxSteps": 8,
            },
        )
        assert session_id is not None
        
        session = store.get_session(session_id)
        assert session is not None
        assert session["name"] == "Test Session"
        assert session["config"]["providerId"] == "openai-local"

    def test_list_sessions(self, store: ConversationStore) -> None:
        """测试列出会话"""
        # 创建多个会话
        sid1 = store.create_session("Session 1")
        sid2 = store.create_session("Session 2")

        # 列出会话
        sessions = store.list_sessions(limit=10)
        assert len(sessions) >= 2
        assert any(s["id"] == sid1 for s in sessions)
        assert any(s["id"] == sid2 for s in sessions)

    def test_list_sessions_sorted_by_recent_update(self, store: ConversationStore) -> None:
        """测试会话按最近更新时间倒序排列。"""
        older_id = store.create_session("Older Session")
        newer_id = store.create_session("Newer Session")

        with store._connect() as conn:
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                ("2026-01-01T00:00:00", older_id),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                ("2026-01-01T00:00:05", newer_id),
            )
            conn.commit()

        sessions = store.list_sessions(limit=10)
        ordered_ids = [session["id"] for session in sessions]
        assert ordered_ids.index(newer_id) < ordered_ids.index(older_id)

    def test_pinned_session_is_ordered_first(self, store: ConversationStore) -> None:
        """测试置顶会话优先显示。"""
        normal_id = store.create_session("Normal Session")
        pinned_id = store.create_session("Pinned Session")
        assert store.update_session_state(pinned_id, pinned=True)

        sessions = store.list_sessions(limit=10)
        ordered_ids = [session["id"] for session in sessions]
        assert ordered_ids.index(pinned_id) < ordered_ids.index(normal_id)

    def test_archived_session_hidden_by_default(self, store: ConversationStore) -> None:
        """测试归档会话默认不出现在会话列表。"""
        active_id = store.create_session("Active Session")
        archived_id = store.create_session("Archived Session")
        assert store.update_session_state(archived_id, archived=True)

        sessions = store.list_sessions(limit=10)
        ids = [session["id"] for session in sessions]
        assert active_id in ids
        assert archived_id not in ids

        archived_only_sessions = store.list_sessions(limit=10, archived_only=True)
        archived_ids = [session["id"] for session in archived_only_sessions]
        assert archived_id in archived_ids

    def test_runtime_session_hidden_by_default(self, store: ConversationStore) -> None:
        normal_id = store.create_session("Normal Session")
        runtime_id = store.create_session("Runtime Session", session_type="schedule-runtime")

        sessions = store.list_sessions(limit=20)
        ids = [session["id"] for session in sessions]
        assert normal_id in ids
        assert runtime_id not in ids

        sessions_with_runtime = store.list_sessions(limit=20, include_runtime=True)
        ids_with_runtime = [session["id"] for session in sessions_with_runtime]
        assert runtime_id in ids_with_runtime

    def test_get_session(self, store: ConversationStore) -> None:
        """测试获取单个会话"""
        session_id = store.create_session(
            name="Test Get",
            config={"maxSteps": 5},
        )

        session = store.get_session(session_id)
        assert session is not None
        assert session["id"] == session_id
        assert session["name"] == "Test Get"
        assert session["config"]["maxSteps"] == 5

    def test_update_session(self, store: ConversationStore) -> None:
        """测试更新会话配置"""
        session_id = store.create_session(
            name="Test Update",
            config={"maxSteps": 8},
        )

        # 更新会话
        success = store.update_session_config(
            session_id,
            {"maxSteps": 10, "providerId": "new-provider"},
        )
        assert success

        session = store.get_session(session_id)
        assert session["config"]["maxSteps"] == 10
        assert session["config"]["providerId"] == "new-provider"

    def test_update_session_name(self, store: ConversationStore) -> None:
        """测试更新会话名称"""
        session_id = store.create_session("Old Name")

        success = store.update_session_name(session_id, "New Name")
        assert success

        session = store.get_session(session_id)
        assert session is not None
        assert session["name"] == "New Name"

    def test_delete_session(self, store: ConversationStore) -> None:
        """测试删除会话"""
        session_id = store.create_session("Test Delete")

        # 删除会话
        success = store.delete_session(session_id)
        assert success

        # 验证会话已删除
        session = store.get_session(session_id)
        assert session is None

    def test_get_nonexistent_session(self, store: ConversationStore) -> None:
        """测试获取不存在的会话"""
        fake_id = str(uuid4())
        session = store.get_session(fake_id)
        assert session is None

    def test_session_task_count(self, store: ConversationStore) -> None:
        """测试会话的任务计数"""
        session_id = store.create_session("Count Test")

        # 创建任务
        task_id = store.create_task(session_id=session_id, goal="Test task")

        # 列出会话，检查任务计数
        sessions = store.list_sessions()
        target = next((s for s in sessions if s["id"] == session_id), None)
        assert target is not None
        assert target["task_count"] == 1


class TestTaskManagement:
    """任务管理测试"""

    def test_create_task(self, store: ConversationStore) -> None:
        """测试创建任务"""
        session_id = store.create_session("Task Session")
        task_id = store.create_task(session_id=session_id, goal="Test goal")
        
        assert task_id is not None
        task = store.get_task(task_id)
        assert task is not None
        assert task["session_id"] == session_id
        assert task["goal"] == "Test goal"
        assert task["status"] == "running"

    def test_save_task(self, store: ConversationStore) -> None:
        """测试保存任务结果"""
        session_id = store.create_session("Task Session")
        task_id = store.create_task(session_id=session_id, goal="Test goal")

        # 保存任务结果
        success = store.save_task(
            task_id=task_id,
            status="completed",
            final_answer="Done",
            steps=[{"step": 1}],
            events=[{"type": "run_start"}, {"type": "llm_pending", "step": 1}],
            duration_ms=1000,
        )
        assert success

        task = store.get_task(task_id)
        assert task["status"] == "completed"
        assert task["final_answer"] == "Done"
        assert task["duration_ms"] == 1000
        assert len(task["steps"]) == 1
        assert len(task["events"]) == 2
        assert task["events"][0]["type"] == "run_start"

    def test_list_tasks_in_session(self, store: ConversationStore) -> None:
        """测试列出会话内的任务"""
        session_id = store.create_session("Task Session")
        
        # 创建多个任务
        tid1 = store.create_task(session_id=session_id, goal="Task 1")
        tid2 = store.create_task(session_id=session_id, goal="Task 2")

        # 列出任务
        tasks = store.list_tasks(session_id=session_id)
        assert len(tasks) == 2
        assert any(t["id"] == tid1 for t in tasks)
        assert any(t["id"] == tid2 for t in tasks)

    def test_get_nonexistent_task(self, store: ConversationStore) -> None:
        """测试获取不存在的任务"""
        fake_id = str(uuid4())
        task = store.get_task(fake_id)
        assert task is None

    def test_delete_session_cascades_tasks(self, store: ConversationStore) -> None:
        """测试删除会话时级联删除任务"""
        session_id = store.create_session("Cascade Test")
        task_id = store.create_task(session_id=session_id, goal="Task")

        # 删除会话
        store.delete_session(session_id)

        # 验证任务也被删除
        task = store.get_task(task_id)
        assert task is None


class TestScheduledTaskManagement:
    """会话定时任务管理测试"""

    def test_existing_schedule_runtime_session_is_migrated_to_owner_session(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "conversation.db"
            store = ConversationStore(db_path=str(db_path))
            session_id = store.create_session("Schedule Session")
            runtime_session_id = store.create_session("Legacy Runtime", session_type="schedule-runtime")
            schedule_id = store.create_scheduled_task(
                session_id=session_id,
                runtime_session_id=runtime_session_id,
                name="历史轮询",
                prompt="执行一次",
                interval_seconds=300,
                enabled=True,
            )

            reopened = ConversationStore(db_path=str(db_path))
            item = reopened.get_scheduled_task(schedule_id)

            assert item is not None
            assert item["session_id"] == session_id
            assert item["runtime_session_id"] == session_id

    def test_create_and_get_scheduled_task_defaults_runtime_to_owner_session(
        self, store: ConversationStore
    ) -> None:
        session_id = store.create_session("Schedule Session")
        schedule_id = store.create_scheduled_task(
            session_id=session_id,
            name="群聊轮询",
            prompt="检查企业微信群最新消息并生成回复",
            interval_seconds=300,
            enabled=True,
        )

        item = store.get_scheduled_task(schedule_id)
        assert item is not None
        assert item["session_id"] == session_id
        assert item["runtime_session_id"] == session_id
        assert item["name"] == "群聊轮询"
        assert item["interval_seconds"] == 300
        assert item["enabled"] is True

    def test_update_scheduled_task_prompt_and_interval(self, store: ConversationStore) -> None:
        session_id = store.create_session("Schedule Session")
        schedule_id = store.create_scheduled_task(
            session_id=session_id,
            name="轮询",
            prompt="旧提示词",
            interval_seconds=120,
            enabled=True,
        )

        ok = store.update_scheduled_task(
            schedule_id=schedule_id,
            prompt="新提示词",
            interval_seconds=600,
        )
        assert ok

        item = store.get_scheduled_task(schedule_id)
        assert item is not None
        assert item["prompt"] == "新提示词"
        assert item["interval_seconds"] == 600

    def test_claim_and_finish_due_scheduled_task(self, store: ConversationStore) -> None:
        session_id = store.create_session("Schedule Session")
        schedule_id = store.create_scheduled_task(
            session_id=session_id,
            name="轮询",
            prompt="执行一次",
            interval_seconds=60,
            enabled=True,
        )

        due = store.claim_due_scheduled_tasks(now_iso="9999-12-31T23:59:59", limit=5)
        assert any(item["id"] == schedule_id for item in due)

        # 已被领取后，不应再次领取
        due_again = store.claim_due_scheduled_tasks(now_iso="9999-12-31T23:59:59", limit=5)
        assert not any(item["id"] == schedule_id for item in due_again)

        done = store.finish_scheduled_task_run(
            schedule_id=schedule_id,
            status="completed",
            task_id="task-1",
            next_run_at="2099-01-01T00:00:00",
            error="",
        )
        assert done

        item = store.get_scheduled_task(schedule_id)
        assert item is not None
        assert item["running"] is False
        assert item["last_status"] == "completed"
        assert item["last_task_id"] == "task-1"

    def test_delete_session_cascades_scheduled_tasks(self, store: ConversationStore) -> None:
        session_id = store.create_session("Cascade Schedule")
        schedule_id = store.create_scheduled_task(
            session_id=session_id,
            name="轮询",
            prompt="执行",
            interval_seconds=60,
            enabled=True,
        )

        assert store.delete_session(session_id)
        assert store.get_scheduled_task(schedule_id) is None

    def test_create_and_finish_scheduled_task_run_record(self, store: ConversationStore) -> None:
        session_id = store.create_session("Run Record Session")
        schedule_id = store.create_scheduled_task(
            session_id=session_id,
            name="轮询",
            prompt="执行",
            interval_seconds=120,
            enabled=True,
        )

        run_id = store.create_scheduled_task_run(
            schedule_id=schedule_id,
            session_id=session_id,
            task_id="task-a",
            trigger_type="manual",
        )
        assert run_id

        ok = store.finish_scheduled_task_run_record(
            run_id=run_id,
            status="completed",
            error="",
            task_id="task-a",
        )
        assert ok

        rows = store.list_scheduled_task_runs(schedule_id=schedule_id, limit=10)
        assert len(rows) == 1
        assert rows[0]["id"] == run_id
        assert rows[0]["trigger_type"] == "manual"
        assert rows[0]["status"] == "completed"
        assert rows[0]["task_id"] == "task-a"

    def test_delete_session_cascades_scheduled_task_runs(self, store: ConversationStore) -> None:
        session_id = store.create_session("Cascade Run Session")
        schedule_id = store.create_scheduled_task(
            session_id=session_id,
            name="轮询",
            prompt="执行",
            interval_seconds=120,
            enabled=True,
        )
        store.create_scheduled_task_run(
            schedule_id=schedule_id,
            session_id=session_id,
            task_id="task-b",
            trigger_type="auto",
        )

        assert store.delete_session(session_id)
        rows = store.list_scheduled_task_runs(schedule_id=schedule_id, limit=10)
        assert rows == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

