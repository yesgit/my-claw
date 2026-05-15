from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class OperationRecord:
    """单次操作记录。"""
    action: str
    timestamp: float
    params: dict[str, Any]
    result: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "timestamp": self.timestamp,
            "params": self.params,
            "result": self.result,
        }


class ComputerState:
    """computer 工具的操作状态管理。

    维护：
    - 最近操作历史（用于调试和审计）
    - 当前活跃窗口句柄（方便连续操作）
    - 已读消息追踪（用于去重）
    """

    MAX_HISTORY = 50

    def __init__(self) -> None:
        self._history: list[OperationRecord] = []
        self._current_hwnd: int | None = None
        self._read_messages: dict[str, str] = {}  # group_key -> last_message_snippet

    # ------------------------------------------------------------------
    # 操作历史
    # ------------------------------------------------------------------

    def record(
        self,
        action: str,
        params: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        """记录一次操作。"""
        entry = OperationRecord(
            action=action,
            timestamp=time.time(),
            params=params,
            result=result,
        )
        self._history.append(entry)
        # 保留最近 N 条
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[-self.MAX_HISTORY:]

    def get_history(self, count: int = 10) -> list[dict[str, Any]]:
        """获取最近 N 条操作历史。"""
        records = self._history[-count:]
        return [r.to_dict() for r in records]

    def clear_history(self) -> None:
        """清空操作历史。"""
        self._history.clear()

    # ------------------------------------------------------------------
    # 当前窗口
    # ------------------------------------------------------------------

    @property
    def current_hwnd(self) -> int | None:
        """获取当前活跃窗口句柄。"""
        return self._current_hwnd

    @current_hwnd.setter
    def current_hwnd(self, hwnd: int | None) -> None:
        self._current_hwnd = hwnd

    # ------------------------------------------------------------------
    # 消息追踪
    # ------------------------------------------------------------------

    def get_last_read_message(self, group_key: str) -> str:
        """获取指定群组最后已读消息摘要。"""
        return self._read_messages.get(group_key, "")

    def set_last_read_message(self, group_key: str, snippet: str) -> None:
        """记录指定群组最后已读消息摘要。"""
        self._read_messages[group_key] = snippet

    def get_all_tracked_groups(self) -> dict[str, str]:
        """获取所有追踪的群组及其最后已读消息。"""
        return dict(self._read_messages)

    # ------------------------------------------------------------------
    # 状态摘要
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """获取当前状态摘要。"""
        return {
            "current_hwnd": self._current_hwnd,
            "history_count": len(self._history),
            "tracked_groups": list(self._read_messages.keys()),
        }