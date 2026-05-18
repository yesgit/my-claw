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
    - status: 执行状态（completed / error / cannot_complete / max_steps_reached）
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
            default_path = Path.home() / ".myclaw" / "conversations.db"
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
                    session_type TEXT NOT NULL DEFAULT 'normal',
                    pinned INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    archived_at TEXT,
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

            # Scheduled tasks 表：会话内可复用的定时任务定义
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    runtime_session_id TEXT,
                    name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    interval_seconds INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    next_run_at TEXT NOT NULL,
                    last_run_at TEXT,
                    last_status TEXT,
                    last_error TEXT,
                    last_task_id TEXT,
                    running INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_session_id
                ON scheduled_tasks (session_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run
                ON scheduled_tasks (enabled, next_run_at)
                """
            )

            # Scheduled task runs 表：定时任务每次执行的历史记录
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_task_runs (
                    id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    task_id TEXT,
                    trigger_type TEXT NOT NULL DEFAULT 'auto',
                    status TEXT NOT NULL DEFAULT 'running',
                    error TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    FOREIGN KEY (schedule_id) REFERENCES scheduled_tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scheduled_task_runs_schedule_id
                ON scheduled_task_runs (schedule_id, started_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scheduled_task_runs_session_id
                ON scheduled_task_runs (session_id, started_at DESC)
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

            # 兼容旧库：补充 sessions.pinned/archived/archived_at 字段
            session_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
            }
            if "pinned" not in session_columns:
                conn.execute(
                    "ALTER TABLE sessions ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
                )
            if "archived" not in session_columns:
                conn.execute(
                    "ALTER TABLE sessions ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
                )
            if "archived_at" not in session_columns:
                conn.execute(
                    "ALTER TABLE sessions ADD COLUMN archived_at TEXT"
                )
            if "session_type" not in session_columns:
                conn.execute(
                    "ALTER TABLE sessions ADD COLUMN session_type TEXT NOT NULL DEFAULT 'normal'"
                )

            # 兼容旧库：补充 scheduled_tasks.running 字段
            scheduled_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(scheduled_tasks)").fetchall()
            }
            if scheduled_columns and "running" not in scheduled_columns:
                conn.execute(
                    "ALTER TABLE scheduled_tasks ADD COLUMN running INTEGER NOT NULL DEFAULT 0"
                )
            if scheduled_columns and "runtime_session_id" not in scheduled_columns:
                conn.execute(
                    "ALTER TABLE scheduled_tasks ADD COLUMN runtime_session_id TEXT"
                )
            if scheduled_columns and "runtime_session_id" in scheduled_columns:
                conn.execute(
                    "UPDATE scheduled_tasks SET runtime_session_id = session_id WHERE runtime_session_id IS NULL OR runtime_session_id != session_id"
                )
            
            # 会话级策略规则表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_policy_rules (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    effect TEXT NOT NULL CHECK(effect IN ('allow', 'deny')),
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_session_policy_rules_session_id
                ON session_policy_rules (session_id)
                """
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

    def create_session(
        self,
        name: str,
        config: dict[str, Any] | None = None,
        session_type: str = "normal",
    ) -> str:
        """创建一个新的会话，返回 session_id。"""
        session_id = str(uuid4())
        now = datetime.now().isoformat(timespec="seconds")
        config_json = json.dumps(config or {}, ensure_ascii=False)
        normalized_type = session_type if session_type in {"normal", "schedule-runtime"} else "normal"
        
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, name, config, session_type, pinned, archived, archived_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, name, config_json, normalized_type, 0, 0, None, now, now),
            )
            conn.commit()
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """获取会话详情。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, config, session_type, pinned, archived, archived_at, created_at, updated_at FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        
        if row is None:
            return None
        
        return {
            "id": row[0],
            "name": row[1],
            "config": json.loads(row[2]),
            "session_type": row[3] or "normal",
            "pinned": bool(row[4]),
            "archived": bool(row[5]),
            "archived_at": row[6],
            "created_at": row[7],
            "updated_at": row[8],
        }

    def list_sessions(
        self,
        limit: int = 20,
        offset: int = 0,
        include_archived: bool = False,
        archived_only: bool = False,
        include_runtime: bool = False,
    ) -> list[dict[str, Any]]:
        """列出所有会话（分页）。"""
        where_clauses: list[str] = []
        params: list[Any] = []
        if archived_only:
            where_clauses.append("archived = 1")
        elif not include_archived:
            where_clauses.append("archived = 0")
        if not include_runtime:
            where_clauses.append("session_type != 'schedule-runtime'")

        where_clause = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, name, config, session_type, pinned, archived, archived_at, created_at, updated_at
                FROM sessions
                {where_clause}
                ORDER BY pinned DESC, updated_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        
        result = []
        for row in rows:
            session_dict = {
                "id": row[0],
                "name": row[1],
                "config": json.loads(row[2]),
                "session_type": row[3] or "normal",
                "pinned": bool(row[4]),
                "archived": bool(row[5]),
                "archived_at": row[6],
                "created_at": row[7],
                "updated_at": row[8],
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

    def update_session_state(
        self,
        session_id: str,
        pinned: bool | None = None,
        archived: bool | None = None,
    ) -> bool:
        """更新会话状态（置顶/归档）。"""
        updates: list[str] = []
        values: list[Any] = []

        if archived is not None:
            if archived:
                updates.extend([
                    "archived = ?",
                    "archived_at = ?",
                    "pinned = ?",
                ])
                values.extend([1, datetime.now().isoformat(timespec="seconds"), 0])
            else:
                updates.extend([
                    "archived = ?",
                    "archived_at = ?",
                ])
                values.extend([0, None])

        if pinned is not None and archived is not True:
            updates.append("pinned = ?")
            values.append(1 if pinned else 0)

        if not updates:
            return False

        updates.append("updated_at = ?")
        values.append(datetime.now().isoformat(timespec="seconds"))
        values.append(session_id)

        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            conn.commit()
        return cursor.rowcount > 0

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

    def append_task_step(self, task_id: str, step_record: dict[str, Any]) -> bool:
        """原子性地向 task 追加一个 step（读取现有 steps → 追加 → 写回）。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT steps FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                return False
            existing_steps: list[dict[str, Any]] = json.loads(row[0])
            existing_steps.append(step_record)
            conn.execute(
                "UPDATE tasks SET steps = ? WHERE id = ?",
                (json.dumps(existing_steps, ensure_ascii=False), task_id),
            )
            conn.commit()
        return True

    def mark_stale_running_tasks(self) -> int:
        """将所有 status='running' 的任务标记为 'interrupted'（后端重启时调用）。"""
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE tasks SET status = 'interrupted' WHERE status = 'running'"
            )
            conn.commit()
            return cursor.rowcount

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

    # ================== Scheduled Task Management (within Session) ==================

    def create_scheduled_task(
        self,
        session_id: str,
        name: str,
        prompt: str,
        interval_seconds: int,
        runtime_session_id: str | None = None,
        enabled: bool = True,
    ) -> str:
        """在会话内创建定时任务，返回 schedule_id。"""
        schedule_id = str(uuid4())
        now = datetime.now().isoformat(timespec="seconds")
        next_run_at = now

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scheduled_tasks (
                    id, session_id, runtime_session_id, name, prompt, interval_seconds, enabled,
                    next_run_at, last_run_at, last_status, last_error, last_task_id,
                    running, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule_id,
                    session_id,
                    runtime_session_id or session_id,
                    name,
                    prompt,
                    interval_seconds,
                    1 if enabled else 0,
                    next_run_at,
                    None,
                    None,
                    None,
                    None,
                    0,
                    now,
                    now,
                ),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            conn.commit()
        return schedule_id

    def get_scheduled_task(self, schedule_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    id, session_id, runtime_session_id, name, prompt, interval_seconds, enabled,
                    next_run_at, last_run_at, last_status, last_error, last_task_id,
                    running, created_at, updated_at
                FROM scheduled_tasks
                WHERE id = ?
                """,
                (schedule_id,),
            ).fetchone()

        if row is None:
            return None

        return {
            "id": row[0],
            "session_id": row[1],
            "runtime_session_id": row[2] or row[1],
            "name": row[3],
            "prompt": row[4],
            "interval_seconds": row[5],
            "enabled": bool(row[6]),
            "next_run_at": row[7],
            "last_run_at": row[8],
            "last_status": row[9],
            "last_error": row[10],
            "last_task_id": row[11],
            "running": bool(row[12]),
            "created_at": row[13],
            "updated_at": row[14],
        }

    def list_scheduled_tasks(
        self,
        session_id: str,
        include_disabled: bool = True,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT
                id, session_id, runtime_session_id, name, prompt, interval_seconds, enabled,
                next_run_at, last_run_at, last_status, last_error, last_task_id,
                running, created_at, updated_at
            FROM scheduled_tasks
            WHERE session_id = ?
        """
        params: list[Any] = [session_id]
        if not include_disabled:
            sql += " AND enabled = 1"
        sql += " ORDER BY created_at DESC"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            {
                "id": row[0],
                "session_id": row[1],
                "runtime_session_id": row[2] or row[1],
                "name": row[3],
                "prompt": row[4],
                "interval_seconds": row[5],
                "enabled": bool(row[6]),
                "next_run_at": row[7],
                "last_run_at": row[8],
                "last_status": row[9],
                "last_error": row[10],
                "last_task_id": row[11],
                "running": bool(row[12]),
                "created_at": row[13],
                "updated_at": row[14],
            }
            for row in rows
        ]

    def update_scheduled_task(
        self,
        schedule_id: str,
        name: str | None = None,
        prompt: str | None = None,
        interval_seconds: int | None = None,
        enabled: bool | None = None,
    ) -> bool:
        updates: list[str] = []
        values: list[Any] = []

        if name is not None:
            updates.append("name = ?")
            values.append(name)
        if prompt is not None:
            updates.append("prompt = ?")
            values.append(prompt)
        if interval_seconds is not None:
            updates.append("interval_seconds = ?")
            values.append(interval_seconds)
        if enabled is not None:
            updates.append("enabled = ?")
            values.append(1 if enabled else 0)
            if enabled:
                updates.append("next_run_at = ?")
                values.append(datetime.now().isoformat(timespec="seconds"))
                updates.append("running = ?")
                values.append(0)

        if not updates:
            return False

        now = datetime.now().isoformat(timespec="seconds")
        updates.append("updated_at = ?")
        values.append(now)
        values.append(schedule_id)

        with self._connect() as conn:
            session_row = conn.execute(
                "SELECT session_id FROM scheduled_tasks WHERE id = ?",
                (schedule_id,),
            ).fetchone()
            cursor = conn.execute(
                f"UPDATE scheduled_tasks SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            if session_row is not None:
                conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE id = ?",
                    (now, session_row[0]),
                )
            conn.commit()
        return cursor.rowcount > 0

    def delete_scheduled_task(self, schedule_id: str) -> bool:
        with self._connect() as conn:
            session_row = conn.execute(
                "SELECT session_id FROM scheduled_tasks WHERE id = ?",
                (schedule_id,),
            ).fetchone()
            cursor = conn.execute(
                "DELETE FROM scheduled_tasks WHERE id = ?",
                (schedule_id,),
            )
            if session_row is not None:
                conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE id = ?",
                    (datetime.now().isoformat(timespec="seconds"), session_row[0]),
                )
            conn.commit()
        return cursor.rowcount > 0

    def claim_due_scheduled_tasks(self, now_iso: str, limit: int = 5) -> list[dict[str, Any]]:
        """领取到期任务，避免同一任务被重复并发执行。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id, session_id, runtime_session_id, name, prompt, interval_seconds, enabled,
                    next_run_at, last_run_at, last_status, last_error, last_task_id,
                    running, created_at, updated_at
                FROM scheduled_tasks
                WHERE enabled = 1 AND running = 0 AND next_run_at <= ?
                ORDER BY next_run_at ASC
                LIMIT ?
                """,
                (now_iso, limit),
            ).fetchall()

            claimed: list[dict[str, Any]] = []
            for row in rows:
                cursor = conn.execute(
                    "UPDATE scheduled_tasks SET running = 1, updated_at = ? WHERE id = ? AND running = 0",
                    (now_iso, row[0]),
                )
                if cursor.rowcount <= 0:
                    continue
                claimed.append(
                    {
                        "id": row[0],
                        "session_id": row[1],
                        "runtime_session_id": row[2] or row[1],
                        "name": row[3],
                        "prompt": row[4],
                        "interval_seconds": row[5],
                        "enabled": bool(row[6]),
                        "next_run_at": row[7],
                        "last_run_at": row[8],
                        "last_status": row[9],
                        "last_error": row[10],
                        "last_task_id": row[11],
                        "running": True,
                        "created_at": row[13],
                        "updated_at": row[14],
                    }
                )
            conn.commit()
        return claimed

    def claim_scheduled_task(self, schedule_id: str) -> dict[str, Any] | None:
        """领取指定定时任务（仅当 enabled=1 且未在运行中）。"""
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    id, session_id, runtime_session_id, name, prompt, interval_seconds, enabled,
                    next_run_at, last_run_at, last_status, last_error, last_task_id,
                    running, created_at, updated_at
                FROM scheduled_tasks
                WHERE id = ?
                """,
                (schedule_id,),
            ).fetchone()
            if row is None or int(row[5]) != 1:
                return None

            cursor = conn.execute(
                "UPDATE scheduled_tasks SET running = 1, updated_at = ? WHERE id = ? AND running = 0",
                (now, schedule_id),
            )
            conn.commit()

        if cursor.rowcount <= 0:
            return None

        return {
            "id": row[0],
            "session_id": row[1],
            "runtime_session_id": row[2] or row[1],
            "name": row[3],
            "prompt": row[4],
            "interval_seconds": row[5],
            "enabled": bool(row[6]),
            "next_run_at": row[7],
            "last_run_at": row[8],
            "last_status": row[9],
            "last_error": row[10],
            "last_task_id": row[11],
            "running": True,
            "created_at": row[13],
            "updated_at": row[14],
        }

    def finish_scheduled_task_run(
        self,
        schedule_id: str,
        status: str,
        task_id: str | None,
        next_run_at: str,
        error: str = "",
    ) -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            session_row = conn.execute(
                "SELECT session_id FROM scheduled_tasks WHERE id = ?",
                (schedule_id,),
            ).fetchone()
            cursor = conn.execute(
                """
                UPDATE scheduled_tasks
                SET
                    running = 0,
                    last_run_at = ?,
                    last_status = ?,
                    last_error = ?,
                    last_task_id = ?,
                    next_run_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, status, error, task_id, next_run_at, now, schedule_id),
            )
            if session_row is not None:
                conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE id = ?",
                    (now, session_row[0]),
                )
            conn.commit()
        return cursor.rowcount > 0

    def release_scheduled_task(self, schedule_id: str, error: str = "") -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scheduled_tasks
                SET running = 0, last_status = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                ("error", error, now, schedule_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def create_scheduled_task_run(
        self,
        schedule_id: str,
        session_id: str,
        task_id: str | None,
        trigger_type: str = "auto",
    ) -> str:
        """创建一条定时任务运行记录，默认状态为 running。"""
        run_id = str(uuid4())
        now = datetime.now().isoformat(timespec="seconds")
        normalized_trigger = trigger_type if trigger_type in {"auto", "manual"} else "auto"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scheduled_task_runs (
                    id, schedule_id, session_id, task_id, trigger_type,
                    status, error, started_at, finished_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    schedule_id,
                    session_id,
                    task_id,
                    normalized_trigger,
                    "running",
                    "",
                    now,
                    None,
                ),
            )
            conn.commit()
        return run_id

    def finish_scheduled_task_run_record(
        self,
        run_id: str,
        status: str,
        error: str = "",
        task_id: str | None = None,
    ) -> bool:
        """结束一条定时任务运行记录。"""
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scheduled_task_runs
                SET status = ?, error = ?, task_id = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, error, task_id, now, run_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def list_scheduled_task_runs(
        self,
        schedule_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """列出指定定时任务的执行历史。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id, schedule_id, session_id, task_id, trigger_type,
                    status, error, started_at, finished_at
                FROM scheduled_task_runs
                WHERE schedule_id = ?
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
                """,
                (schedule_id, limit, offset),
            ).fetchall()

        return [
            {
                "id": row[0],
                "schedule_id": row[1],
                "session_id": row[2],
                "task_id": row[3],
                "trigger_type": row[4],
                "status": row[5],
                "error": row[6],
                "started_at": row[7],
                "finished_at": row[8],
            }
            for row in rows
        ]

    # ================== Session Policy Rules ==================

    def create_session_rule(
        self,
        session_id: str,
        tool: str,
        action: str,
        resource: str,
        effect: str,
    ) -> str:
        """创建会话级策略规则，返回 rule_id。"""
        rule_id = str(uuid4())
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO session_policy_rules (id, session_id, tool, action, resource, effect, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (rule_id, session_id, tool, action, resource, effect, now),
            )
            conn.commit()
        return rule_id

    def list_session_rules(self, session_id: str) -> list[dict[str, Any]]:
        """列出会话的所有策略规则。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, tool, action, resource, effect, created_at
                FROM session_policy_rules
                WHERE session_id = ?
                ORDER BY created_at DESC
                """,
                (session_id,),
            ).fetchall()

        return [
            {
                "id": row[0],
                "session_id": row[1],
                "tool": row[2],
                "action": row[3],
                "resource": row[4],
                "effect": row[5],
                "created_at": row[6],
            }
            for row in rows
        ]

    def get_session_rule(self, rule_id: str) -> dict[str, Any] | None:
        """获取单条会话策略规则。"""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, session_id, tool, action, resource, effect, created_at
                FROM session_policy_rules
                WHERE id = ?
                """,
                (rule_id,),
            ).fetchone()

        if row is None:
            return None

        return {
            "id": row[0],
            "session_id": row[1],
            "tool": row[2],
            "action": row[3],
            "resource": row[4],
            "effect": row[5],
            "created_at": row[6],
        }

    def delete_session_rule(self, rule_id: str) -> bool:
        """删除一条会话策略规则。"""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM session_policy_rules WHERE id = ?",
                (rule_id,),
            )
            conn.commit()
        return cursor.rowcount > 0
