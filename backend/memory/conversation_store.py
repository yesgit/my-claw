from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class ConversationStore:
    """对话历史持久化存储（SQLite）。

    每条记录包含：
    - id: 唯一标识
    - goal: 用户目标
    - status: 执行状态（completed / error / max_steps_reached）
    - final_answer: 最终回答
    - steps: 执行步骤（JSON）
    - events: 执行事件流（JSON，按顺序）
    - duration_ms: 耗时（毫秒）
    - created_at: 创建时间
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path == ":memory:":
            # 内存数据库需要特殊处理，保持连接打开
            self._db_path = ":memory:"
            self._memory_conn: sqlite3.Connection | None = None
        else:
            default_path = Path.cwd() / "data" / "conversations.db"
            self._db_path = Path(db_path) if db_path else default_path
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._memory_conn = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._db_path == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:")
                self._memory_conn.execute("PRAGMA foreign_keys = ON")
            return self._memory_conn
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            # Sessions 表：会话配置和元数据
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    config TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sessions_created_at
                ON sessions (created_at DESC)
                """
            )
            
            # Tasks 表：会话内的任务
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    final_answer TEXT NOT NULL DEFAULT '',
                    steps TEXT NOT NULL DEFAULT '[]',
                    events TEXT NOT NULL DEFAULT '[]',
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_session_id
                ON tasks (session_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_created_at
                ON tasks (created_at DESC)
                """
            )

            # 兼容旧库：补充 tasks.events 字段
            task_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "events" not in task_columns:
                conn.execute(
                    "ALTER TABLE tasks ADD COLUMN events TEXT NOT NULL DEFAULT '[]'"
                )
            
            # 保持对旧 conversations 表的兼容性
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

    # ================== Session Management ==================

    def create_session(self, name: str, config: dict[str, Any] | None = None) -> str:
        """创建一个新的会话，返回 session_id。"""
        session_id = str(uuid4())
        now = datetime.now().isoformat(timespec="seconds")
        config_json = json.dumps(config or {}, ensure_ascii=False)
        
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, name, config, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, name, config_json, now, now),
            )
            conn.commit()
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """获取会话详情。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, config, created_at, updated_at FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        
        if row is None:
            return None
        
        return {
            "id": row[0],
            "name": row[1],
            "config": json.loads(row[2]),
            "created_at": row[3],
            "updated_at": row[4],
        }

    def list_sessions(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        """列出所有会话（分页）。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, config, created_at, updated_at
                FROM sessions
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        
        result = []
        for row in rows:
            session_dict = {
                "id": row[0],
                "name": row[1],
                "config": json.loads(row[2]),
                "created_at": row[3],
                "updated_at": row[4],
            }
            # 统计该会话的任务数
            with self._connect() as conn:
                count_row = conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE session_id = ?",
                    (row[0],),
                ).fetchone()
            session_dict["task_count"] = count_row[0] if count_row else 0
            result.append(session_dict)
        
        return result

    def update_session_config(self, session_id: str, config: dict[str, Any]) -> bool:
        """更新会话配置。"""
        now = datetime.now().isoformat(timespec="seconds")
        config_json = json.dumps(config, ensure_ascii=False)
        
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET config = ?, updated_at = ? WHERE id = ?",
                (config_json, now, session_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def update_session_name(self, session_id: str, name: str) -> bool:
        """更新会话名称。"""
        now = datetime.now().isoformat(timespec="seconds")
        normalized_name = name.strip()
        if not normalized_name:
            return False

        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET name = ?, updated_at = ? WHERE id = ?",
                (normalized_name, now, session_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def delete_session(self, session_id: str) -> bool:
        """删除会话及其所有任务。"""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM sessions WHERE id = ?",
                (session_id,),
            )
            conn.commit()
        return cursor.rowcount > 0

    # ================== Task Management (within Session) ==================

    def create_task(self, session_id: str, goal: str) -> str:
        """在会话内创建一个任务，返回 task_id。"""
        task_id = str(uuid4())
        now = datetime.now().isoformat(timespec="seconds")
        
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (id, session_id, goal, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, session_id, goal, "running", now),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            conn.commit()
        return task_id

    def save_task(
        self,
        task_id: str,
        status: str,
        final_answer: str = "",
        steps: list[dict[str, Any]] | None = None,
        events: list[dict[str, Any]] | None = None,
        duration_ms: int = 0,
    ) -> bool:
        """更新任务的执行结果。"""
        with self._connect() as conn:
            session_row = conn.execute(
                "SELECT session_id FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            cursor = conn.execute(
                """
                UPDATE tasks
                SET status = ?, final_answer = ?, steps = ?, events = ?, duration_ms = ?
                WHERE id = ?
                """,
                (
                    status,
                    final_answer,
                    json.dumps(steps or [], ensure_ascii=False),
                    json.dumps(events or [], ensure_ascii=False),
                    duration_ms,
                    task_id,
                ),
            )
            if session_row is not None:
                conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE id = ?",
                    (datetime.now().isoformat(timespec="seconds"), session_row[0]),
                )
            conn.commit()
        return cursor.rowcount > 0

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """获取单个任务的详情。"""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, session_id, goal, status, final_answer, steps, events, duration_ms, created_at
                FROM tasks
                WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
        
        if row is None:
            return None
        
        return {
            "id": row[0],
            "session_id": row[1],
            "goal": row[2],
            "status": row[3],
            "final_answer": row[4],
            "steps": json.loads(row[5]),
            "events": json.loads(row[6] or "[]"),
            "duration_ms": row[7],
            "created_at": row[8],
        }

    def list_tasks(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """列出会话内的任务（分页）。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, goal, status, final_answer, steps, events, duration_ms, created_at
                FROM tasks
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (session_id, limit, offset),
            ).fetchall()
        
        return [
            {
                "id": row[0],
                "session_id": row[1],
                "goal": row[2],
                "status": row[3],
                "final_answer": row[4],
                "steps": json.loads(row[5]),
                "events": json.loads(row[6] or "[]"),
                "duration_ms": row[7],
                "created_at": row[8],
            }
            for row in rows
        ]
