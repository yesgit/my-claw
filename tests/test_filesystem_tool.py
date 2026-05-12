from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.models import OperationRequest
from backend.tools.filesystem.tool import FilesystemTool


class TestFilesystemTool(unittest.TestCase):
    def test_describe_schema(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tool = FilesystemTool(allowed_directories=[tmp_dir])
            desc = tool.describe()

            # 新版统一字段
            self.assertEqual(desc["tool"], "filesystem")
            self.assertEqual(desc["type"], "local")
            self.assertTrue(any(action["name"] == "write_file" for action in desc["actions"]))
            self.assertIn("input_schema", desc)

            # 旧字段兼容
            self.assertEqual(desc["tool_name"], "filesystem")
            self.assertIn("write_file", desc["supported_actions"])
            self.assertEqual(len(desc["allowed_directories"]), 1)

    def test_write_and_read_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "note.txt"
            tool = FilesystemTool()

            write_result = tool.execute(
                OperationRequest(
                    tool="filesystem",
                    action="write_file",
                    resource=str(target),
                    params={"mode": "overwrite", "content": "hello"},
                )
            )
            read_result = tool.execute(
                OperationRequest(
                    tool="filesystem",
                    action="read_file",
                    resource=str(target),
                    params={},
                )
            )

            self.assertTrue(write_result["ok"])
            self.assertEqual(read_result["content"].strip(), "hello")
            self.assertEqual(read_result["bytes_read"], len("hello\n".encode("utf-8")))

    def test_list_dir(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "b.txt").write_text("b", encoding="utf-8")
            (root / "a.txt").write_text("a", encoding="utf-8")
            (root / "subdir").mkdir()

            tool = FilesystemTool()
            result = tool.execute(
                OperationRequest(
                    tool="filesystem",
                    action="list_dir",
                    resource=str(root),
                    params={},
                )
            )

            names = [entry["name"] for entry in result["entries"]]
            self.assertEqual(names, ["a.txt", "b.txt", "subdir"])
            self.assertEqual(result["count"], 3)
            self.assertTrue(any(entry["is_dir"] for entry in result["entries"] if entry["name"] == "subdir"))

    def test_read_missing_file_raises(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tool = FilesystemTool()
            missing = Path(tmp_dir) / "missing.txt"

            with self.assertRaises(FileNotFoundError):
                tool.execute(
                    OperationRequest(
                        tool="filesystem",
                        action="read_file",
                        resource=str(missing),
                        params={},
                    )
                )

    def test_list_non_dir_raises(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            target = root / "file.txt"
            target.write_text("x", encoding="utf-8")
            tool = FilesystemTool()

            with self.assertRaises(NotADirectoryError):
                tool.execute(
                    OperationRequest(
                        tool="filesystem",
                        action="list_dir",
                        resource=str(target),
                        params={},
                    )
                )

    def test_copy_and_move_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "source.txt"
            copied = root / "nested" / "copied.txt"
            moved = root / "nested" / "moved.txt"
            source.write_text("payload", encoding="utf-8")
            tool = FilesystemTool()

            copy_result = tool.execute(
                OperationRequest(
                    tool="filesystem",
                    action="copy_file",
                    resource=str(source),
                    params={"destination": str(copied)},
                )
            )
            move_result = tool.execute(
                OperationRequest(
                    tool="filesystem",
                    action="move_file",
                    resource=str(copied),
                    params={"destination": str(moved)},
                )
            )

            self.assertTrue(copy_result["ok"])
            self.assertTrue(move_result["ok"])
            self.assertTrue(moved.exists())
            self.assertFalse(copied.exists())
            self.assertEqual(moved.read_text(encoding="utf-8"), "payload")

    def test_delete_file_and_directory(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            file_target = root / "delete-me.txt"
            dir_target = root / "folder"
            nested = dir_target / "nested.txt"
            file_target.write_text("bye", encoding="utf-8")
            dir_target.mkdir()
            nested.write_text("bye", encoding="utf-8")
            tool = FilesystemTool()

            file_result = tool.execute(
                OperationRequest(
                    tool="filesystem",
                    action="delete_path",
                    resource=str(file_target),
                    params={},
                )
            )
            dir_result = tool.execute(
                OperationRequest(
                    tool="filesystem",
                    action="delete_path",
                    resource=str(dir_target),
                    params={},
                )
            )

            self.assertEqual(file_result["deleted_kind"], "file")
            self.assertEqual(dir_result["deleted_kind"], "directory")
            self.assertFalse(file_target.exists())
            self.assertFalse(dir_target.exists())


if __name__ == "__main__":
    unittest.main()
