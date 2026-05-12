from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.memory.conversation_store import ConversationStore


class TestConversationStore(unittest.TestCase):
    def test_save_and_list_conversations(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conv.db")
            store.save_conversation(
                conversation_id="c-1",
                goal="测试任务",
                status="completed",
                final_answer="完成",
                steps=[{"step": 1, "action": "read_file"}],
                duration_ms=1234,
            )

            items = store.list_conversations()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["id"], "c-1")
            self.assertEqual(items[0]["goal"], "测试任务")
            self.assertEqual(items[0]["status"], "completed")
            self.assertEqual(items[0]["final_answer"], "完成")
            self.assertEqual(items[0]["duration_ms"], 1234)
            self.assertEqual(len(items[0]["steps"]), 1)

    def test_get_conversation(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conv.db")
            store.save_conversation(
                conversation_id="c-1",
                goal="测试",
                status="completed",
            )

            item = store.get_conversation("c-1")
            self.assertIsNotNone(item)
            assert item is not None
            self.assertEqual(item["goal"], "测试")

            missing = store.get_conversation("missing")
            self.assertIsNone(missing)

    def test_delete_conversation(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conv.db")
            store.save_conversation(conversation_id="c-1", goal="测试", status="completed")

            self.assertTrue(store.delete_conversation("c-1"))
            self.assertFalse(store.delete_conversation("missing"))
            self.assertEqual(len(store.list_conversations()), 0)

    def test_clear_all(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conv.db")
            store.save_conversation(conversation_id="c-1", goal="a", status="completed")
            store.save_conversation(conversation_id="c-2", goal="b", status="error")

            deleted = store.clear_all()
            self.assertEqual(deleted, 2)
            self.assertEqual(len(store.list_conversations()), 0)

    def test_count(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conv.db")
            self.assertEqual(store.count(), 0)

            store.save_conversation(conversation_id="c-1", goal="a", status="completed")
            self.assertEqual(store.count(), 1)

            store.save_conversation(conversation_id="c-2", goal="b", status="completed")
            self.assertEqual(store.count(), 2)

    def test_list_with_limit_and_offset(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conv.db")
            for i in range(5):
                store.save_conversation(
                    conversation_id=f"c-{i}",
                    goal=f"任务{i}",
                    status="completed",
                )

            items = store.list_conversations(limit=2, offset=0)
            self.assertEqual(len(items), 2)

            items_page2 = store.list_conversations(limit=2, offset=2)
            self.assertEqual(len(items_page2), 2)

    def test_update_existing_conversation(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ConversationStore(Path(tmp_dir) / "conv.db")
            store.save_conversation(
                conversation_id="c-1",
                goal="原始",
                status="completed",
                final_answer="旧回答",
            )

            store.save_conversation(
                conversation_id="c-1",
                goal="更新",
                status="error",
                final_answer="新回答",
            )

            item = store.get_conversation("c-1")
            assert item is not None
            self.assertEqual(item["goal"], "更新")
            self.assertEqual(item["status"], "error")
            self.assertEqual(item["final_answer"], "新回答")


if __name__ == "__main__":
    unittest.main()
