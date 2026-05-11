from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.models import OperationRequest
from backend.policy_guard.guard import PolicyGuard
from backend.tool_router.router import ToolRouter


class TestFilesystemApprovalChain(unittest.TestCase):
    def test_read_file_through_guard_and_router(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "note.txt"
            target.write_text("hello chain", encoding="utf-8")
            guard = PolicyGuard(input_func=lambda _: "y")
            router = ToolRouter()
            operation = OperationRequest(
                tool="filesystem",
                action="read_file",
                resource=str(target),
                params={},
            )

            self.assertTrue(guard.approve(operation))
            result = router.execute(operation)
            self.assertEqual(result["content"].strip(), "hello chain")

    def test_list_dir_through_guard_and_router(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "alpha.txt").write_text("a", encoding="utf-8")
            (root / "beta.txt").write_text("b", encoding="utf-8")
            guard = PolicyGuard(input_func=lambda _: "y")
            router = ToolRouter()
            operation = OperationRequest(
                tool="filesystem",
                action="list_dir",
                resource=str(root),
                params={},
            )

            self.assertTrue(guard.approve(operation))
            result = router.execute(operation)
            names = [entry["name"] for entry in result["entries"]]
            self.assertEqual(names, ["alpha.txt", "beta.txt"])

    def test_copy_move_delete_through_guard_and_router(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "source.txt"
            copied = root / "copied.txt"
            moved = root / "moved.txt"
            folder = root / "folder"
            source.write_text("x", encoding="utf-8")
            folder.mkdir()
            (folder / "inside.txt").write_text("y", encoding="utf-8")

            guard = PolicyGuard(input_func=lambda _: "y")
            router = ToolRouter()

            copy_op = OperationRequest(
                tool="filesystem",
                action="copy_file",
                resource=str(source),
                params={"destination": str(copied)},
            )
            move_op = OperationRequest(
                tool="filesystem",
                action="move_file",
                resource=str(copied),
                params={"destination": str(moved)},
            )
            delete_op = OperationRequest(
                tool="filesystem",
                action="delete_path",
                resource=str(folder),
                params={},
            )

            self.assertTrue(guard.approve(copy_op))
            copy_result = router.execute(copy_op)
            self.assertTrue(copy_result["ok"])

            self.assertTrue(guard.approve(move_op))
            move_result = router.execute(move_op)
            self.assertTrue(move_result["ok"])

            self.assertTrue(guard.approve(delete_op))
            delete_result = router.execute(delete_op)
            self.assertEqual(delete_result["deleted_kind"], "directory")
            self.assertTrue(moved.exists())
            self.assertFalse(copied.exists())
            self.assertFalse(folder.exists())


if __name__ == "__main__":
    unittest.main()
