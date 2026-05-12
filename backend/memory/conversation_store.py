from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class ConversationStore:
    """对话历史持久化存储（SQLite）。

    每条记录包含：
    - id: 唯一标识
    - goal: 用户目标
    - status: 执行状态（completed / error / max_steps_reached）
    - final_answer: 最终回答
    - steps: 执行步骤（JSON）
    - duration_ms: 耗时（毫秒）
    - created_at: 创建时间
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        default_path = Path.cwd() / "data" / "conversations.db"
        self._db_path = Path(db_path) if db_path else default_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    final_answer TEXT NOT NULL DEFAULT '',
                    steps TEXT NOT NULL DEFAULT '[]',
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversations_created_at
                ON conversations (created_at DESC)
                """
            )
            conn.commit()

    def save_conversation(
        self,
        conversation_id: str,
        goal: str,
        status: str,
        final_answer: str = "",
        steps: list[dict[str, Any]] | None = None,
        duration_ms: int = 0,
    ) -> None:
        """保存一条对话记录。"""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO conversations (id, goal, status, final_answer, steps, duration_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    goal,
                    status,
                    final_answer,
                    json.dumps(steps or [], ensure_ascii=False),
                    duration_ms,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()

    def list_conversations(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        """列出最近的对话记录。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, goal, status, final_answer, steps, duration_ms, created_at
                FROM conversations
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        return [
            {
                "id": row[0],
                "goal": row[1],
                "status": row[2],
                "final_answer": row[3],
                "steps": json.loads(row[4]),
                "duration_ms": row[5],
                "created_at": row[6],
            }
            for row in rows
        ]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """获取单条对话记录。"""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, goal, status, final_answer, steps, duration_ms, created_at
                FROM conversations
                WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()

        if row is None:
            return None

        return {
            "id": row[0],
            "goal": row[1],
            "status": row[2],
            "final_answer": row[3],
            "steps": json.loads(row[4]),
            "duration_ms": row[5],
            "created_at": row[6],
        }

    def delete_conversation(self, conversation_id: str) -> bool:
        """删除一条对话记录。"""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM conversations WHERE id = ?",
                (conversation_id,),
            )
            conn.commit()
        return cursor.rowcount > 0

    def clear_all(self) -> int:
        """清空所有对话记录。"""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM conversations")
            conn.commit()
        return cursor.rowcount

    def count(self) -> int:
        """返回对话记录总数。"""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()
        return row[0] if row else 0
