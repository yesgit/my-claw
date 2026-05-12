from __future__ import annotations

import os
import shutil
from pathlib import Path

from backend.models import OperationRequest


class FilesystemTool:
    tool_name = "filesystem"
    description = "文件系统操作工具，支持读写文件、目录列表、复制/移动/删除等操作"
    supported_actions = {
        "write_file": "medium",
        "read_file": "medium",
        "list_dir": "medium",
        "move_file": "medium",
        "copy_file": "medium",
        "delete_path": "high",
    }

    def __init__(self, allowed_directories: list[str] | None = None) -> None:
        """初始化文件系统工具。

        Args:
            allowed_directories: 允许操作的目录列表。
                                 所有文件操作必须在此范围内的路径。
                                 为 None 时不限制（兼容旧行为）。
        """
        self._allowed_directories: list[Path] | None = None
        if allowed_directories is not None:
            self._allowed_directories = [Path(d).resolve() for d in allowed_directories]

    def describe(self) -> dict:
        """返回工具的标准自描述信息。"""
        return {
            "tool_name": self.tool_name,
            "description": self.description,
            "supported_actions": dict(self.supported_actions),
            "allowed_directories": [str(d) for d in (self._allowed_directories or [])],
        }

    def _check_path(self, *paths: str | Path) -> None:
        """校验所有路径是否在允许的目录范围内。"""
        if self._allowed_directories is None:
            return  # 不限制

        for raw in paths:
            target = Path(raw).resolve()
            allowed = any(
                target == ad or _is_subpath(target, ad)
                for ad in self._allowed_directories
            )
            if not allowed:
                raise PermissionError(
                    f"路径不在允许的目录范围内: {target}。"
                    f" 允许的目录: {[str(d) for d in self._allowed_directories]}"
                )

    def execute(self, operation: OperationRequest) -> dict:
        if operation.action == "write_file":
            return self._write_file(operation)
        if operation.action == "read_file":
            return self._read_file(operation)
        if operation.action == "list_dir":
            return self._list_dir(operation)
        if operation.action == "move_file":
            return self._move_file(operation)
        if operation.action == "copy_file":
            return self._copy_file(operation)
        if operation.action == "delete_path":
            return self._delete_path(operation)

        raise ValueError(f"不支持的 action: {operation.action}")

    def _write_file(self, operation: OperationRequest) -> dict:
        target = Path(operation.resource)
        self._check_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)

        mode = operation.params.get("mode", "overwrite")
        content = operation.params.get("content", "")
        open_mode = "a" if mode == "append" else "w"

        with target.open(open_mode, encoding="utf-8") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")

        return {
            "ok": True,
            "tool": self.tool_name,
            "action": operation.action,
            "resource": str(target),
            "bytes_written": len(content.encode("utf-8")),
            "mode": mode,
        }

    def _read_file(self, operation: OperationRequest) -> dict:
        target = Path(operation.resource)
        self._check_path(target)
        if not target.exists():
            raise FileNotFoundError(f"文件不存在: {target}")
        if target.is_dir():
            raise IsADirectoryError(f"目标是目录，不能读取为文件: {target}")

        content = target.read_text(encoding="utf-8")
        return {
            "ok": True,
            "tool": self.tool_name,
            "action": operation.action,
            "resource": str(target),
            "content": content,
            "bytes_read": len(content.encode("utf-8")),
        }

    def _list_dir(self, operation: OperationRequest) -> dict:
        target = Path(operation.resource)
        self._check_path(target)
        if not target.exists():
            raise FileNotFoundError(f"目录不存在: {target}")
        if not target.is_dir():
            raise NotADirectoryError(f"目标不是目录: {target}")

        entries = []
        for child in sorted(target.iterdir(), key=lambda item: item.name.lower()):
            entries.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "is_dir": child.is_dir(),
                }
            )

        return {
            "ok": True,
            "tool": self.tool_name,
            "action": operation.action,
            "resource": str(target),
            "entries": entries,
            "count": len(entries),
        }

    def _move_file(self, operation: OperationRequest) -> dict:
        source = Path(operation.resource)
        destination_value = operation.params.get("destination")
        if not destination_value:
            raise ValueError("move_file 需要 params.destination")
        destination = Path(destination_value)

        self._check_path(source, destination)

        if not source.exists():
            raise FileNotFoundError(f"源路径不存在: {source}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))

        return {
            "ok": True,
            "tool": self.tool_name,
            "action": operation.action,
            "resource": str(source),
            "destination": str(destination),
        }

    def _copy_file(self, operation: OperationRequest) -> dict:
        source = Path(operation.resource)
        destination_value = operation.params.get("destination")
        if not destination_value:
            raise ValueError("copy_file 需要 params.destination")
        destination = Path(destination_value)

        self._check_path(source, destination)

        if not source.exists():
            raise FileNotFoundError(f"源路径不存在: {source}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            if destination.exists():
                raise FileExistsError(f"目标已存在: {destination}")
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)

        return {
            "ok": True,
            "tool": self.tool_name,
            "action": operation.action,
            "resource": str(source),
            "destination": str(destination),
        }

    def _delete_path(self, operation: OperationRequest) -> dict:
        target = Path(operation.resource)
        self._check_path(target)
        if not target.exists():
            raise FileNotFoundError(f"路径不存在: {target}")

        deleted_kind = "directory" if target.is_dir() else "file"
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

        return {
            "ok": True,
            "tool": self.tool_name,
            "action": operation.action,
            "resource": str(target),
            "deleted_kind": deleted_kind,
        }


def _is_subpath(child: Path, parent: Path) -> bool:
    """判断 child 是否是 parent 的子路径（含多级嵌套）。"""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False
