from __future__ import annotations

from backend.models import OperationRequest


class SchedulerTool:
    """内置定时任务管理工具。

    允许 LLM 在会话内创建、查看、更新、删除定时任务。
    定时任务触发时会以 prompt 作为用户提问，在绑定的运行时会话中执行一次 ReAct 链路。
    """

    tool_name = "scheduler"
    description = "定时任务管理工具，可以创建、查看、更新、删除当前会话的定时任务"
    supported_actions = {
        "create_schedule": "low",
        "list_schedules": "low",
        "delete_schedule": "low",
        "update_schedule": "low",
    }

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id

    def describe(self) -> dict:
        actions = [
            {"name": action, "default_risk": risk}
            for action, risk in self.supported_actions.items()
        ]
        return {
            # 新版统一字段
            "tool": self.tool_name,
            "type": "local",
            "actions": actions,
            "input_schema": {
                "create_schedule": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "定时任务名称"},
                        "prompt": {
                            "type": "string",
                            "description": "定时触发时发送给助手的提示词（作为用户提问）",
                        },
                        "interval_seconds": {
                            "type": "integer",
                            "description": "执行间隔（秒），最小 30",
                        },
                        "enabled": {
                            "type": "boolean",
                            "description": "是否立即启用，默认 true",
                        },
                    },
                    "required": ["name", "prompt", "interval_seconds"],
                },
                "list_schedules": {
                    "type": "object",
                    "properties": {},
                },
                "delete_schedule": {
                    "type": "object",
                    "properties": {
                        "schedule_id": {"type": "string", "description": "定时任务 ID"},
                    },
                    "required": ["schedule_id"],
                },
                "update_schedule": {
                    "type": "object",
                    "properties": {
                        "schedule_id": {"type": "string", "description": "定时任务 ID"},
                        "name": {"type": "string", "description": "新名称"},
                        "prompt": {"type": "string", "description": "新提示词"},
                        "interval_seconds": {
                            "type": "integer",
                            "description": "新执行间隔（秒），最小 30",
                        },
                        "enabled": {"type": "boolean", "description": "是否启用"},
                    },
                    "required": ["schedule_id"],
                },
            },
            # 兼容旧字段
            "tool_name": self.tool_name,
            "description": self.description,
            "supported_actions": dict(self.supported_actions),
        }

    def execute(self, operation: OperationRequest) -> dict:
        if operation.action == "create_schedule":
            return self._create_schedule(operation)
        if operation.action == "list_schedules":
            return self._list_schedules()
        if operation.action == "delete_schedule":
            return self._delete_schedule(operation)
        if operation.action == "update_schedule":
            return self._update_schedule(operation)
        raise ValueError(f"scheduler 工具不支持的动作: {operation.action}")

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _create_schedule(self, operation: OperationRequest) -> dict:
        # 延迟导入，避免循环依赖
        from backend.memory.conversation_store import ConversationStore  # noqa: PLC0415

        params = operation.params or {}
        name = str(params.get("name", "")).strip()
        prompt = str(params.get("prompt", "")).strip()
        raw_interval = params.get("interval_seconds", 0)
        try:
            interval_seconds = int(raw_interval)
        except (TypeError, ValueError):
            return {"ok": False, "error": "interval_seconds 必须是整数"}
        enabled = bool(params.get("enabled", True))

        if not name:
            return {"ok": False, "error": "name 不能为空"}
        if not prompt:
            return {"ok": False, "error": "prompt 不能为空"}
        if interval_seconds < 30:
            return {"ok": False, "error": "interval_seconds 最小为 30 秒"}

        store = ConversationStore()
        session = store.get_session(self._session_id)
        if session is None:
            return {"ok": False, "error": "当前会话不存在"}

        # 创建专用运行时会话，继承父会话配置
        runtime_name = f"{name} · 定时执行"
        runtime_session_id = store.create_session(
            name=runtime_name,
            config=session.get("config", {}),
            session_type="schedule-runtime",
        )

        schedule_id = store.create_scheduled_task(
            session_id=self._session_id,
            runtime_session_id=runtime_session_id,
            name=name,
            prompt=prompt,
            interval_seconds=interval_seconds,
            enabled=enabled,
        )
        schedule = store.get_scheduled_task(schedule_id)
        interval_desc = _format_interval(interval_seconds)
        return {
            "ok": True,
            "schedule_id": schedule_id,
            "schedule": schedule,
            "message": f"定时任务「{name}」已创建，{interval_desc}执行一次，提示词：{prompt}",
        }

    def _list_schedules(self) -> dict:
        from backend.memory.conversation_store import ConversationStore  # noqa: PLC0415

        store = ConversationStore()
        schedules = store.list_scheduled_tasks(session_id=self._session_id, include_disabled=True)
        if not schedules:
            return {"ok": True, "schedules": [], "count": 0, "message": "当前会话没有定时任务"}
        summaries = [
            {
                "id": s["id"],
                "name": s["name"],
                "prompt": s["prompt"],
                "interval_seconds": s["interval_seconds"],
                "enabled": s["enabled"],
                "last_status": s["last_status"],
                "next_run_at": s["next_run_at"],
            }
            for s in schedules
        ]
        return {"ok": True, "schedules": summaries, "count": len(summaries)}

    def _delete_schedule(self, operation: OperationRequest) -> dict:
        from backend.memory.conversation_store import ConversationStore  # noqa: PLC0415

        params = operation.params or {}
        schedule_id = str(params.get("schedule_id", "")).strip()
        if not schedule_id:
            return {"ok": False, "error": "schedule_id 不能为空"}

        store = ConversationStore()
        schedule = store.get_scheduled_task(schedule_id)
        if schedule is None:
            return {"ok": False, "error": f"定时任务不存在: {schedule_id}"}
        if schedule.get("session_id") != self._session_id:
            return {"ok": False, "error": "无权操作其他会话的定时任务"}

        deleted = store.delete_scheduled_task(schedule_id)
        if deleted:
            return {"ok": True, "message": f"定时任务「{schedule['name']}」已删除"}
        return {"ok": False, "error": "删除失败"}

    def _update_schedule(self, operation: OperationRequest) -> dict:
        from backend.memory.conversation_store import ConversationStore  # noqa: PLC0415

        params = operation.params or {}
        schedule_id = str(params.get("schedule_id", "")).strip()
        if not schedule_id:
            return {"ok": False, "error": "schedule_id 不能为空"}

        store = ConversationStore()
        schedule = store.get_scheduled_task(schedule_id)
        if schedule is None:
            return {"ok": False, "error": f"定时任务不存在: {schedule_id}"}
        if schedule.get("session_id") != self._session_id:
            return {"ok": False, "error": "无权操作其他会话的定时任务"}

        name: str | None = None
        prompt: str | None = None
        interval_seconds: int | None = None
        enabled: bool | None = None

        if "name" in params:
            name = str(params["name"]).strip() or None
        if "prompt" in params:
            prompt = str(params["prompt"]).strip() or None
        if "interval_seconds" in params:
            try:
                interval_seconds = int(params["interval_seconds"])
            except (TypeError, ValueError):
                return {"ok": False, "error": "interval_seconds 必须是整数"}
            if interval_seconds < 30:
                return {"ok": False, "error": "interval_seconds 最小为 30 秒"}
        if "enabled" in params:
            enabled = bool(params["enabled"])

        updated = store.update_scheduled_task(
            schedule_id=schedule_id,
            name=name,
            prompt=prompt,
            interval_seconds=interval_seconds,
            enabled=enabled,
        )
        if updated:
            schedule = store.get_scheduled_task(schedule_id)
            return {"ok": True, "schedule": schedule, "message": "定时任务已更新"}
        return {"ok": False, "error": "更新失败（没有需要变更的字段）"}


def _format_interval(seconds: int) -> str:
    """将秒数格式化为人类可读的间隔描述。"""
    if seconds < 60:
        return f"每 {seconds} 秒"
    if seconds < 3600:
        minutes = seconds // 60
        return f"每 {minutes} 分钟"
    if seconds < 86400:
        hours = seconds // 3600
        return f"每 {hours} 小时"
    days = seconds // 86400
    return f"每 {days} 天"
