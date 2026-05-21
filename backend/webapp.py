from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from queue import Queue
from threading import Event, Lock, Thread
from typing import Any
from urllib import error, request
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from fastapi import File, Form, UploadFile
from pydantic import BaseModel, Field

from backend.agent import ReactAgent
from backend.llm import OpenAICompatibleChatClient, OpenAICompatibleConfig, LLMClientError
from backend.mcp import MCPClientManager, MCPServerClient, StdIOTransport, load_mcp_server_configs
from backend.memory.rule_store import RuleStore
from backend.memory.conversation_store import ConversationStore
from backend.policy_guard.guard import PolicyGuard
from backend.tool_router.router import ToolRouter

# ---- 路径解析（支持 PyInstaller 打包） ----
# 打包模式：通过环境变量获取路径（由 desktop_app.py 注入）
_BUNDLE_DIR = Path(os.environ.get("MYCLAW_BUNDLE_DIR", Path(__file__).resolve().parents[1]))
_DATA_DIR = Path(os.environ.get("MYCLAW_DATA_DIR", _BUNDLE_DIR / "data"))

import logging

_webapp_logger = logging.getLogger("myclaw.webapp")

ROOT = _BUNDLE_DIR
STATIC_DIR = ROOT / "ui" / "web"

_webapp_logger.info("[webapp] ROOT = %s", ROOT)
_webapp_logger.info("[webapp] STATIC_DIR = %s", STATIC_DIR)
_webapp_logger.info("[webapp] STATIC_DIR exists = %s", STATIC_DIR.exists())
if STATIC_DIR.exists():
    _webapp_logger.info("[webapp] STATIC_DIR files = %s", [f.name for f in STATIC_DIR.iterdir()][:20])

app = FastAPI(title="MyClaw Web UI", version="0.2.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
def on_startup() -> None:
    _webapp_logger.info("[webapp] FastAPI startup event, starting scheduler...")
    # 将所有残留 running 的任务标记为 interrupted（后端重启后无法恢复）
    try:
        store = ConversationStore()
        count = store.mark_stale_running_tasks()
        if count > 0:
            _webapp_logger.info("[startup] 已将 %d 个残留 running 任务标记为 interrupted", count)
    except Exception:  # noqa: BLE001
        pass
    _start_scheduler_if_needed()


@app.on_event("shutdown")
def on_shutdown() -> None:
    _stop_scheduler()


class ReactRunRequest(BaseModel):
    goal: str = Field(min_length=1)
    providerId: str | None = None
    modelId: str | None = None
    llmBaseUrl: str | None = None
    llmApiKey: str | None = None
    llmModel: str | None = None
    llmTimeout: float | None = Field(default=None, ge=1.0, le=300.0)
    maxSteps: int = Field(default=50, ge=1, le=100)
    approvalDecision: str | None = None
    mcpConfig: str | None = None
    jsonMode: bool | None = None
    filesystemAllowedDirs: list[str] | None = None


# ================= Session API Models =================

class SessionConfigPayload(BaseModel):
    """会话配置"""
    providerId: str | None = None
    modelId: str | None = None
    llmBaseUrl: str | None = None
    llmApiKey: str | None = None
    llmModel: str | None = None
    llmTimeout: float | None = Field(default=None, ge=1.0, le=300.0)
    maxSteps: int = Field(default=50, ge=1, le=100)
    mcpConfig: str | None = None
    mcpServers: list[dict[str, Any]] | None = None
    jsonMode: bool | None = None
    filesystemAllowedDirs: list[str] | None = None


class CreateSessionRequest(BaseModel):
    """创建会话请求"""
    name: str = ""
    seedGoal: str = ""
    sessionType: str | None = None
    config: SessionConfigPayload | None = None


class SessionRenameRequest(BaseModel):
    """会话重命名请求"""
    name: str = Field(min_length=1)

class SessionStateRequest(BaseModel):
    """更新会话状态请求"""
    pinned: bool | None = None
    archived: bool | None = None


class SessionTaskRequest(BaseModel):
    """在会话内发起任务请求"""
    goal: str = Field(min_length=1)
    approvalDecision: str | None = None


class ScheduledTaskCreateRequest(BaseModel):
    """创建会话定时任务请求"""
    name: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    intervalSeconds: int = Field(ge=30, le=86400)
    enabled: bool = True


class ScheduledTaskUpdateRequest(BaseModel):
    """更新会话定时任务请求"""
    name: str | None = Field(default=None, min_length=1)
    prompt: str | None = Field(default=None, min_length=1)
    intervalSeconds: int | None = Field(default=None, ge=30, le=86400)
    enabled: bool | None = None


class ProviderModel(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    model: str = Field(min_length=1)
    flash: bool = False
    vision: bool = False


class ModelProvider(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    baseUrl: str = Field(min_length=1)
    apiKeyEnvVar: str = ""  # 旧字段，仅用于读取旧配置时的兼容，不再参与任何解析
    apiKey: str = ""  # 直接持久化的 API Key
    timeout: float = Field(default=60.0, ge=1.0, le=300.0)
    jsonMode: bool = True
    models: list[ProviderModel] = Field(default_factory=list)


class ModelConfigPayload(BaseModel):
    defaultProviderId: str = Field(min_length=1)
    defaultModelId: str = Field(min_length=1)
    providers: list[ModelProvider] = Field(default_factory=list)


class ModelConnectionTestRequest(BaseModel):
    providerId: str | None = None
    modelId: str | None = None
    baseUrl: str | None = None
    model: str | None = None
    apiKey: str = ""
    timeout: float | None = Field(default=None, ge=1.0, le=300.0)
    jsonMode: bool | None = None


class ModelDiscoverRequest(BaseModel):
    baseUrl: str = Field(min_length=1)
    apiKey: str = ""


class ApprovalDecisionPayload(BaseModel):
    decision: str = Field(min_length=1)


class MCPConfigPayload(BaseModel):
    defaultConfigPath: str = ""
    servers: list[dict[str, Any]] = Field(default_factory=list)


class MCPServerPayload(BaseModel):
    name: str = Field(min_length=1)
    command: list[str] = Field(min_length=1)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


class MCPConfigValidateRequest(BaseModel):
    configPath: str | None = None


class MCPServerConnectionTestRequest(BaseModel):
    server: dict[str, Any]


MODEL_CONFIG_PATH = _DATA_DIR / "model_profiles.json"
MCP_CONFIG_PATH = _DATA_DIR / "mcp_config.json"
UPLOAD_DIR = _DATA_DIR / "uploads"

ALLOWED_APPROVAL_DECISIONS = {"1", "2", "3", "4", "5", "6", "7", "y", "n"}

_MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB


def _save_uploaded_files(session_id: str, files: list[UploadFile]) -> list[dict[str, str]]:
    """保存上传文件到 data/uploads/{session_id}/，返回文件信息列表。"""
    if not files:
        return []
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict[str, str]] = []
    for f in files:
        if not f.filename:
            continue
        # 安全文件名：去掉路径分隔符
        safe_name = f.filename.replace("/", "_").replace("\\", "_").replace("..", "_")
        target = session_dir / safe_name
        # 同名文件加后缀
        counter = 1
        while target.exists():
            stem = target.stem
            suffix = target.suffix
            target = session_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        content = f.file.read(_MAX_UPLOAD_SIZE + 1)
        if len(content) > _MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail=f"文件 {safe_name} 超过 20MB 限制")
        target.write_bytes(content)
        saved.append({
            "filename": safe_name,
            "path": str(target.resolve()),
            "size": len(content),
            "content_type": f.content_type or "application/octet-stream",
        })
    return saved


def _compute_generalize_options(tool: str, resource: str) -> list[dict[str, str]]:
    """根据操作信息，计算审批时可用的泛化选项列表。

    返回每项的 {id, label, decision, scope, resource_scope}：
    - id 用于前端 key
    - label 显示给人看
    - decision 是提交给后端的审批编号
    - scope 标识生命周期：once / session / persistent
    - resource_scope 标识资源范围：exact / folder / parent / tool_all / exact_path
    """
    options: list[dict[str, str]] = [
        {"id": "once", "label": "允许一次", "decision": "1", "scope": "once", "resource_scope": "exact"},
        {"id": "session", "label": "本会话允许", "decision": "2", "scope": "session", "resource_scope": "exact"},
    ]
    if resource and resource not in ("", "*", "/"):
        from pathlib import PurePosixPath  # noqa: PLC0415
        try:
            p = PurePosixPath(resource)
            if p.parent != p:
                options.append({
                    "id": "folder", "label": f"允许 {p.parent}/*", "decision": "3",
                    "scope": "session", "resource_scope": "folder",
                })
                if p.parent.parent != p.parent:
                    options.append({
                        "id": "parent", "label": f"允许 {p.parent.parent}/**", "decision": "4",
                        "scope": "session", "resource_scope": "parent",
                    })
        except Exception:  # noqa: BLE001
            pass

    options.append({
        "id": "tool_all", "label": f"允许 {tool}/*", "decision": "5",
        "scope": "persistent", "resource_scope": "tool_all",
    })
    options.append({
        "id": "always", "label": "始终允许（精确路径）", "decision": "6",
        "scope": "persistent", "resource_scope": "exact_path",
    })
    options.append({
        "id": "deny", "label": "始终拒绝", "decision": "7",
        "scope": "persistent", "resource_scope": "exact_path",
    })
    return options


@dataclass(slots=True)
class PendingApproval:
    event: Event
    decision: str | None = None


_approval_lock = Lock()
_pending_approvals: dict[tuple[str, str], PendingApproval] = {}
_scheduler_stop_event = Event()
_scheduler_thread: Thread | None = None
_scheduler_lock = Lock()


def _normalize_approval_decision(decision: str | None) -> str | None:
    if decision is None:
        return None
    value = decision.strip().lower()
    if not value:
        return None
    if value not in ALLOWED_APPROVAL_DECISIONS:
        raise HTTPException(status_code=400, detail="approvalDecision 必须是 1/2/3/4/y/n")
    return value


def _register_pending_approval(run_id: str, approval_id: str) -> None:
    key = (run_id, approval_id)
    with _approval_lock:
        _pending_approvals[key] = PendingApproval(event=Event())


def _wait_pending_approval(run_id: str, approval_id: str, timeout_sec: float = 300.0) -> str | None:
    key = (run_id, approval_id)
    with _approval_lock:
        pending = _pending_approvals.get(key)
    if pending is None:
        return None

    finished = pending.event.wait(timeout=timeout_sec)
    with _approval_lock:
        latest = _pending_approvals.pop(key, None)
    if not finished or latest is None:
        return None
    return latest.decision


def _submit_pending_approval(run_id: str, approval_id: str, decision: str) -> bool:
    key = (run_id, approval_id)
    with _approval_lock:
        pending = _pending_approvals.get(key)
        if pending is None:
            return False
        pending.decision = decision
        pending.event.set()
    return True


def _clear_run_pending_approvals(run_id: str) -> None:
    with _approval_lock:
        keys = [key for key in _pending_approvals if key[0] == run_id]
        for key in keys:
            pending = _pending_approvals.pop(key)
            pending.event.set()


def _extract_session_id_from_run_id(run_id: str) -> str | None:
    prefix = "session-"
    marker = "-task-"
    if not run_id.startswith(prefix):
        return None
    suffix = run_id[len(prefix):]
    marker_index = suffix.find(marker)
    if marker_index <= 0:
        return None
    return suffix[:marker_index]


def _list_pending_approvals_for_session(session_id: str) -> list[dict[str, str]]:
    with _approval_lock:
        rows: list[dict[str, str]] = []
        for run_id, approval_id in _pending_approvals:
            if _extract_session_id_from_run_id(run_id) != session_id:
                continue
            rows.append({"run_id": run_id, "approval_id": approval_id})
    return rows


def _now_iso_seconds() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _compute_next_run_at(interval_seconds: int) -> str:
    return (datetime.now() + timedelta(seconds=interval_seconds)).isoformat(timespec="seconds")


def _build_schedule_management_context(store: ConversationStore, session_id: str) -> str:
    """为定时任务会话中的用户主动对话构建上下文。

    LLM 角色：定时任务管理助手，帮助用户创建、编辑、查询、测试定时任务。
    上下文包含当前会话内所有定时任务的列表和详情。
    """
    from backend.tools.scheduler.tool import _format_interval  # noqa: PLC0415

    all_schedules = store.list_scheduled_tasks(session_id=session_id, include_disabled=True)
    if not all_schedules:
        return (
            "你是定时任务管理助手。当前会话还没有定时任务，用户可能会要求你创建、查询或管理定时任务。"
            "请根据用户需求使用 scheduler 工具完成操作。"
        )

    schedule_lines: list[str] = []
    for s in all_schedules:
        s_name = str(s.get("name", "")).strip()
        s_prompt = str(s.get("prompt", "")).strip()
        s_interval = int(s.get("interval_seconds", 0) or 0)
        s_enabled = "启用" if s.get("enabled", True) else "禁用"
        s_last_status = s.get("last_status") or "无"
        s_last_error = s.get("last_error") or ""
        s_last_run_at = s.get("last_run_at") or "无"
        s_next_run_at = s.get("next_run_at") or "无"
        line = (
            f"  - ID: {s['id']}, 名称: {s_name}, 提示词: {s_prompt}, "
            f"间隔: {_format_interval(s_interval)}, 状态: {s_enabled}, "
            f"上次执行: {s_last_status}, 上次执行时间: {s_last_run_at}, "
            f"下次执行时间: {s_next_run_at}"
        )
        if s_last_error:
            line += f", 上次错误: {s_last_error}"
        schedule_lines.append(line)

    schedule_list = "\n".join(schedule_lines)
    return (
        "你是定时任务管理助手，帮助用户管理当前会话的定时任务。"
        "你可以使用 scheduler 工具来创建、查询、更新、删除定时任务。\n\n"
        f"## 当前会话的定时任务列表（共 {len(all_schedules)} 个）\n"
        f"{schedule_list}"
    )


def _build_scheduled_task_context(
    store: ConversationStore,
    session_id: str,
    schedule: dict[str, Any],
    prompt: str,
) -> str:
    """为定时任务执行构建包含上下文信息的 goal，让 LLM 了解当前工作环境。

    上下文包括：
    1. 当前定时任务详情（名称、提示词、间隔、上次执行状态）
    2. 会话内全部定时任务列表
    3. 近期任务执行历史
    """
    from backend.tools.scheduler.tool import _format_interval  # noqa: PLC0415

    schedule_id = str(schedule.get("id", ""))
    schedule_name = str(schedule.get("name", "")).strip()
    interval_seconds = int(schedule.get("interval_seconds", 0) or 0)
    last_status = schedule.get("last_status") or ""
    last_error = schedule.get("last_error") or ""

    # ---- 当前任务详情 ----
    current_task_lines: list[str] = [
        f"当前定时任务: 名称「{schedule_name}」, 提示词「{prompt}」, 间隔 {_format_interval(interval_seconds)}",
    ]
    if last_status:
        current_task_lines.append(f"上次执行状态: {last_status}")
    if last_error:
        current_task_lines.append(f"上次执行错误: {last_error}")

    # ---- 会话内全部定时任务列表 ----
    all_schedules = store.list_scheduled_tasks(session_id=session_id, include_disabled=True)
    schedule_list_lines: list[str] = []
    for s in all_schedules:
        s_name = str(s.get("name", "")).strip()
        s_prompt = str(s.get("prompt", "")).strip()
        s_interval = int(s.get("interval_seconds", 0) or 0)
        s_enabled = "启用" if s.get("enabled", True) else "禁用"
        s_last_status = s.get("last_status") or "无"
        is_current = " ← 当前任务" if s.get("id") == schedule_id else ""
        schedule_list_lines.append(
            f"  - 名称: {s_name}, 提示词: {s_prompt}, 间隔: {_format_interval(s_interval)}, "
            f"状态: {s_enabled}, 上次执行: {s_last_status}{is_current}"
        )

    # ---- 近期任务执行历史 ----
    recent_tasks = store.list_tasks(session_id=session_id, limit=6, offset=0)
    history_lines: list[str] = []
    for item in reversed(recent_tasks):
        goal = str(item.get("goal", "")).strip()
        answer = str(item.get("final_answer", "")).strip()
        status = str(item.get("status", "")).strip()
        if goal:
            history_lines.append(f"用户: {goal}")
        if answer:
            history_lines.append(f"助手: {answer}")
        elif status:
            history_lines.append(f"助手: [status={status}]")

    # ---- 拼装最终 goal ----
    parts: list[str] = [
        "你是定时任务执行代理。你的唯一职责是：执行并完成下方指定的定时任务。",
        "不要创建、修改或删除任何定时任务，只需按照提示词完成当前工作。\n",
        "## 当前定时任务",
        *current_task_lines,
    ]

    if schedule_list_lines:
        parts.append("\n## 会话内所有定时任务（仅供参考，不要修改）")
        parts.extend(schedule_list_lines)

    if history_lines:
        parts.append("\n## 近期执行历史")
        parts.extend(history_lines)

    parts.append(f"\n现在请执行当前定时任务的提示词：{prompt}")

    return "\n".join(parts)


def _run_scheduled_task_once(schedule: dict[str, Any], trigger_type: str = "auto") -> None:
    schedule_id = str(schedule.get("id", ""))
    owner_session_id = str(schedule.get("session_id", ""))
    session_id = str(schedule.get("runtime_session_id") or owner_session_id)
    prompt = str(schedule.get("prompt", "")).strip()
    interval_seconds = int(schedule.get("interval_seconds", 0) or 0)

    store = ConversationStore()
    if not schedule_id or not session_id or not prompt or interval_seconds <= 0:
        if schedule_id:
            store.release_scheduled_task(schedule_id, error="定时任务配置无效")
        return

    session = store.get_session(session_id)
    if session is None:
        store.release_scheduled_task(schedule_id, error="会话不存在")
        return

    session_config = session.get("config", {})
    run_request = ReactRunRequest(
        goal=prompt,
        providerId=session_config.get("providerId"),
        modelId=session_config.get("modelId"),
        llmBaseUrl=session_config.get("llmBaseUrl"),
        llmApiKey=session_config.get("llmApiKey"),
        llmModel=session_config.get("llmModel"),
        llmTimeout=session_config.get("llmTimeout"),
        maxSteps=session_config.get("maxSteps", 50),
        approvalDecision="1",
        mcpConfig=session_config.get("mcpConfig"),
        jsonMode=session_config.get("jsonMode"),
        filesystemAllowedDirs=session_config.get("filesystemAllowedDirs"),
    )

    task_id = store.create_task(session_id=session_id, goal=prompt)
    run_record_id = store.create_scheduled_task_run(
        schedule_id=schedule_id,
        session_id=session_id,
        task_id=task_id,
        trigger_type=trigger_type,
    )
    started_at = perf_counter()

    # ---- 构建定时任务上下文，让 LLM 了解当前工作环境 ----
    contextual_goal = _build_scheduled_task_context(
        store=store,
        session_id=session_id,
        schedule=schedule,
        prompt=prompt,
    )

    try:
        rule_store = RuleStore()
        guard = PolicyGuard(rule_store=rule_store, decision_func=lambda _op, _prompt: "1")
        client = OpenAICompatibleChatClient(_resolve_llm_config(run_request))
        mcp_manager = _build_mcp_manager_for_request(run_request.mcpConfig)
        router = ToolRouter(mcp_manager=mcp_manager, filesystem_allowed_dirs=run_request.filesystemAllowedDirs)
        agent = ReactAgent(
            client=client,
            guard=guard,
            router=router,
            max_steps=run_request.maxSteps,
        )
        try:
            result = agent.run(contextual_goal)
        finally:
            mcp_manager.close_all()

        duration_ms = int((perf_counter() - started_at) * 1000)
        store.save_task(
            task_id=task_id,
            status=result.status,
            final_answer=result.final_answer,
            steps=result.steps,
            events=[],
            duration_ms=duration_ms,
        )
        store.finish_scheduled_task_run(
            schedule_id=schedule_id,
            status=result.status,
            task_id=task_id,
            next_run_at=_compute_next_run_at(interval_seconds),
            error="",
        )
        store.finish_scheduled_task_run_record(
            run_id=run_record_id,
            status=result.status,
            error="",
            task_id=task_id,
        )
    except Exception as exc:  # noqa: BLE001
        duration_ms = int((perf_counter() - started_at) * 1000)
        try:
            store.save_task(
                task_id=task_id,
                status="error",
                final_answer=f"定时任务执行异常：{exc}",
                steps=[],
                events=[],
                duration_ms=duration_ms,
            )
        except Exception:  # noqa: BLE001
            pass
        store.finish_scheduled_task_run(
            schedule_id=schedule_id,
            status="error",
            task_id=task_id,
            next_run_at=_compute_next_run_at(interval_seconds),
            error=str(exc),
        )
        store.finish_scheduled_task_run_record(
            run_id=run_record_id,
            status="error",
            error=str(exc),
            task_id=task_id,
        )


def _scheduled_task_worker() -> None:
    while not _scheduler_stop_event.is_set():
        try:
            store = ConversationStore()
            due_items = store.claim_due_scheduled_tasks(now_iso=_now_iso_seconds(), limit=5)
            for item in due_items:
                Thread(target=_run_scheduled_task_once, args=(item, "auto"), daemon=True).start()
        except Exception:  # noqa: BLE001
            pass
        _scheduler_stop_event.wait(timeout=2.0)


def _start_scheduler_if_needed() -> None:
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            return
        _scheduler_stop_event.clear()
        _scheduler_thread = Thread(target=_scheduled_task_worker, daemon=True)
        _scheduler_thread.start()


def _stop_scheduler() -> None:
    global _scheduler_thread
    with _scheduler_lock:
        _scheduler_stop_event.set()
        _scheduler_thread = None


def _default_model_config() -> ModelConfigPayload:
    return ModelConfigPayload(
        defaultProviderId="openai-local",
        defaultModelId="gpt-4.1-mini",
        providers=[
            ModelProvider(
                id="openai-local",
                name="Local Default",
                baseUrl="http://localhost:8000/v1",
                apiKeyEnvVar="",
                timeout=60.0,
                jsonMode=True,
                models=[
                    ProviderModel(
                        id="gpt-4.1-mini",
                        name="GPT 4.1 Mini",
                        model="gpt-4.1-mini",
                    )
                ],
            )
        ],
    )


def _resolve_api_key(provider: ModelProvider, inline_key: str = "") -> str:
    """优先使用内联 key，其次 provider.apiKey。"""
    if inline_key:
        return inline_key
    return provider.apiKey or ""


def _load_model_config() -> ModelConfigPayload:
    if not MODEL_CONFIG_PATH.exists():
        return _default_model_config()

    try:
        payload = json.loads(MODEL_CONFIG_PATH.read_text(encoding="utf-8"))
        return ModelConfigPayload.model_validate(payload)
    except Exception:  # noqa: BLE001
        return _default_model_config()


def _save_model_config(config: ModelConfigPayload) -> None:
    MODEL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_CONFIG_PATH.write_text(
        json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _default_mcp_config() -> MCPConfigPayload:
    return MCPConfigPayload(defaultConfigPath="", servers=[])


def _load_mcp_config() -> MCPConfigPayload:
    if not MCP_CONFIG_PATH.exists():
        return _default_mcp_config()

    try:
        payload = json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))
        config = MCPConfigPayload.model_validate(payload)
        normalized_servers: list[dict[str, Any]] = []
        for item in config.servers:
            try:
                server = MCPServerPayload.model_validate(item)
            except Exception:  # noqa: BLE001
                continue
            normalized_servers.append(server.model_dump(mode="json"))
        config.servers = normalized_servers
        return config
    except Exception:  # noqa: BLE001
        return _default_mcp_config()


def _save_mcp_config(config: MCPConfigPayload) -> None:
    MCP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    MCP_CONFIG_PATH.write_text(
        json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _resolve_mcp_config_path(request_path: str | None) -> str | None:
    if request_path and request_path.strip():
        return request_path.strip()

    config = _load_mcp_config()
    if config.defaultConfigPath.strip():
        return config.defaultConfigPath.strip()
    return None


def _coerce_inline_mcp_servers(raw_servers: list[dict[str, Any]]) -> list[MCPServerPayload]:
    servers: list[MCPServerPayload] = []
    for item in raw_servers:
        try:
            server = MCPServerPayload.model_validate(item)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"MCP server 配置非法: {exc}") from exc
        servers.append(server)

    names = [item.name for item in servers]
    if len(names) != len(set(names)):
        raise HTTPException(status_code=400, detail="MCP servers.name 不能重复")
    return servers


def _validate_model_config(config: ModelConfigPayload) -> None:
    if not config.providers:
        raise HTTPException(status_code=400, detail="providers 不能为空")

    provider_ids = [item.id for item in config.providers]
    if len(provider_ids) != len(set(provider_ids)):
        raise HTTPException(status_code=400, detail="providers.id 不能重复")

    provider_map = {item.id: item for item in config.providers}
    if config.defaultProviderId not in provider_map:
        raise HTTPException(status_code=400, detail="defaultProviderId 必须存在于 providers")

    for provider in config.providers:
        if not provider.models:
            raise HTTPException(status_code=400, detail=f"provider {provider.id} 必须至少包含一个 model")
        model_ids = [model.id for model in provider.models]
        if len(model_ids) != len(set(model_ids)):
            raise HTTPException(status_code=400, detail=f"provider {provider.id} 的 model.id 不能重复")

    default_provider = provider_map[config.defaultProviderId]
    if config.defaultModelId not in {item.id for item in default_provider.models}:
        raise HTTPException(status_code=400, detail="defaultModelId 必须存在于默认 provider 的 models")


def _resolve_llm_config(payload: ReactRunRequest) -> OpenAICompatibleConfig:
    inline_api_key = (payload.llmApiKey or "").strip()
    if payload.llmBaseUrl and payload.llmModel and inline_api_key:
        return OpenAICompatibleConfig(
            base_url=payload.llmBaseUrl,
            api_key=inline_api_key,
            model=payload.llmModel,
            timeout=payload.llmTimeout or 60.0,
            json_mode=True if payload.jsonMode is None else payload.jsonMode,
        )

    config = _load_model_config()
    target_provider_id = payload.providerId or config.defaultProviderId
    provider = next((item for item in config.providers if item.id == target_provider_id), None)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"provider 不存在: {target_provider_id}")

    model_id = payload.modelId or (config.defaultModelId if provider.id == config.defaultProviderId else provider.models[0].id)
    selected_model = next((item for item in provider.models if item.id == model_id), None)
    if selected_model is None:
        selected_model = provider.models[0]

    api_key = _resolve_api_key(provider, payload.llmApiKey or "")
    return OpenAICompatibleConfig(
        base_url=provider.baseUrl,
        api_key=api_key,
        model=selected_model.model,
        timeout=payload.llmTimeout or provider.timeout,
        json_mode=provider.jsonMode if payload.jsonMode is None else payload.jsonMode,
    )


def _resolve_session_llm_config(config: SessionConfigPayload | None) -> OpenAICompatibleConfig:
    payload = ReactRunRequest(
        goal="生成会话名称",
        providerId=config.providerId if config else None,
        modelId=config.modelId if config else None,
        llmBaseUrl=config.llmBaseUrl if config else None,
        llmApiKey=config.llmApiKey if config else None,
        llmModel=config.llmModel if config else None,
        llmTimeout=config.llmTimeout if config else None,
        jsonMode=config.jsonMode if config else None,
    )
    return _resolve_llm_config(payload)


def _resolve_flash_llm_config() -> OpenAICompatibleConfig:
    """查找第一个标记为 flash 的模型；找不到则 fallback 到默认主力模型。"""
    config = _load_model_config()
    for provider in config.providers:
        for model in provider.models:
            if model.flash:
                api_key = _resolve_api_key(provider)
                return OpenAICompatibleConfig(
                    base_url=provider.baseUrl,
                    api_key=api_key,
                    model=model.model,
                    timeout=provider.timeout,
                    json_mode=provider.jsonMode,
                )

    # fallback：使用默认主力模型
    default_provider = next(
        (item for item in config.providers if item.id == config.defaultProviderId),
        config.providers[0] if config.providers else None,
    )
    if default_provider is None:
        raise HTTPException(status_code=400, detail="无可用的 LLM 模型配置")

    default_model = next(
        (item for item in default_provider.models if item.id == config.defaultModelId),
        default_provider.models[0] if default_provider.models else None,
    )
    if default_model is None:
        raise HTTPException(status_code=400, detail="默认 provider 没有可用模型")

    api_key = _resolve_api_key(default_provider)
    return OpenAICompatibleConfig(
        base_url=default_provider.baseUrl,
        api_key=api_key,
        model=default_model.model,
        timeout=default_provider.timeout,
        json_mode=default_provider.jsonMode,
    )


def _resolve_vision_llm_config() -> OpenAICompatibleConfig:
    """查找第一个标记为 vision 的模型；找不到则 fallback 到默认主力模型。

    用于截图识别等需要视觉/多模态能力的场景。
    """
    config = _load_model_config()
    for provider in config.providers:
        for model in provider.models:
            if model.vision:
                api_key = _resolve_api_key(provider)
                return OpenAICompatibleConfig(
                    base_url=provider.baseUrl,
                    api_key=api_key,
                    model=model.model,
                    timeout=provider.timeout,
                    json_mode=provider.jsonMode,
                )

    # fallback：使用默认主力模型
    default_provider = next(
        (item for item in config.providers if item.id == config.defaultProviderId),
        config.providers[0] if config.providers else None,
    )
    if default_provider is None:
        raise HTTPException(status_code=400, detail="无可用的 LLM 模型配置")

    default_model = next(
        (item for item in default_provider.models if item.id == config.defaultModelId),
        default_provider.models[0] if default_provider.models else None,
    )
    if default_model is None:
        raise HTTPException(status_code=400, detail="默认 provider 没有可用模型")

    api_key = _resolve_api_key(default_provider)
    return OpenAICompatibleConfig(
        base_url=default_provider.baseUrl,
        api_key=api_key,
        model=default_model.model,
        timeout=default_provider.timeout,
        json_mode=default_provider.jsonMode,
    )


def _fallback_session_name(seed_goal: str = "") -> str:
    trimmed_goal = seed_goal.strip()
    if trimmed_goal:
        compact_goal = " ".join(trimmed_goal.split())
        return compact_goal[:24].rstrip(" ,，。！？!?；;") or compact_goal
    return f"会话 {datetime.now().strftime('%m-%d %H:%M')}"


def _normalize_session_name(raw_name: str) -> str:
    text = raw_name.strip()
    if not text:
        return ""

    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            candidate = payload.get("name") or payload.get("title")
            if isinstance(candidate, str):
                text = candidate.strip()

    text = text.strip().strip("\"'“”‘’`")
    text = " ".join(text.split())
    text = text.strip(" ,，。！？!?；;：:")
    if len(text) > 24:
        text = text[:24].rstrip(" ,，。！？!?；;：:")
    return text


def _generate_session_name(seed_goal: str, config: SessionConfigPayload | None) -> str:
    fallback = _fallback_session_name(seed_goal)
    if not seed_goal.strip():
        return fallback

    try:
        llm_config = _resolve_flash_llm_config()
        client = OpenAICompatibleChatClient(llm_config)
        raw_name = client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是会话命名助手。请根据用户的首个问题生成一个简洁的中文会话标题。"
                        "要求：优先 4 到 12 个汉字；避免使用“会话”“聊天”“任务”“帮我”等泛词；"
                        "不要编号、不要标点、不要引号。只返回 JSON 对象，格式为 {\"name\":\"标题\"}。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"首个问题：{seed_goal.strip()}",
                },
            ]
        )
        normalized = _normalize_session_name(raw_name)
        return normalized or fallback
    except Exception:  # noqa: BLE001
        return fallback


def _regenerate_schedule_session_name(session_id: str) -> None:
    """根据会话内所有定时任务的内容，调用 LLM 重新生成会话摘要名称。

    如果 LLM 判定现有名称仍然准确，则不修改。
    """
    try:
        store = ConversationStore()
        session = store.get_session(session_id)
        if session is None:
            return

        schedules = store.list_scheduled_tasks(session_id=session_id, include_disabled=True)
        if not schedules:
            return

        current_name = str(session.get("name") or "").strip()

        # 拼接定时任务摘要
        schedule_lines: list[str] = []
        for idx, s in enumerate(schedules, 1):
            s_name = str(s.get("name") or "").strip()
            s_prompt = str(s.get("prompt") or "").strip()
            s_interval = s.get("interval_seconds", 0)
            schedule_lines.append(f"{idx}. 名称: {s_name}, 提示词: {s_prompt}, 间隔: {s_interval}秒")

        schedule_summary = "\n".join(schedule_lines)

        # 从会话配置解析 LLM 参数
        session_config = session.get("config", {})
        config_payload: SessionConfigPayload | None = None
        if isinstance(session_config, dict):
            config_payload = SessionConfigPayload.model_validate(session_config)

        llm_config = _resolve_flash_llm_config()
        client = OpenAICompatibleChatClient(llm_config)

        system_prompt = (
            "你是会话命名助手。以下是当前会话名称和该会话内的所有定时任务摘要。"
            + "请判断现有名称是否仍能准确概括这些定时任务的内容。"
            + "如果可以，直接返回原名称；否则生成一个更准确的新名称。"
            + "要求：优先 4 到 12 个汉字；避免使用「会话」「聊天」「任务」「帮我」等泛词；"
            + "不要编号、不要标点、不要引号。只返回 JSON 对象，格式为 {\"name\":\"标题\"}。"
        )
        user_prompt = f"当前会话名称：「{current_name}」\n定时任务列表：\n{schedule_summary}"
        raw_name = client.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

        normalized = _normalize_session_name(raw_name)
        if not normalized:
            return

        # 名称没变则跳过写入
        if normalized == current_name:
            return

        store.update_session_name(session_id, normalized)
    except Exception:  # noqa: BLE001
        return


def _resolve_test_llm_config(payload: ModelConnectionTestRequest) -> OpenAICompatibleConfig:
    inline_api_key = (payload.apiKey or "").strip()
    if payload.baseUrl and payload.model and inline_api_key:
        return OpenAICompatibleConfig(
            base_url=payload.baseUrl,
            api_key=inline_api_key,
            model=payload.model,
            timeout=payload.timeout or 20.0,
            json_mode=True if payload.jsonMode is None else payload.jsonMode,
        )

    config = _load_model_config()
    target_provider_id = payload.providerId or config.defaultProviderId
    provider = next((item for item in config.providers if item.id == target_provider_id), None)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"provider 不存在: {target_provider_id}")

    model_id = payload.modelId or (config.defaultModelId if provider.id == config.defaultProviderId else provider.models[0].id)
    selected_model = next((item for item in provider.models if item.id == model_id), None)
    if selected_model is None:
        selected_model = provider.models[0]

    api_key = _resolve_api_key(provider, payload.apiKey)
    return OpenAICompatibleConfig(
        base_url=provider.baseUrl,
        api_key=api_key,
        model=selected_model.model,
        timeout=payload.timeout or provider.timeout,
        json_mode=provider.jsonMode if payload.jsonMode is None else payload.jsonMode,
    )



def _build_mcp_manager(config_path: str | None) -> MCPClientManager:
    manager = MCPClientManager()
    server_configs = []
    if config_path:
        server_configs = load_mcp_server_configs(config_path)

    for server_config in server_configs:
        transport = StdIOTransport(
            command=server_config.command,
            cwd=server_config.cwd,
            env=server_config.env,
        )
        client = MCPServerClient(server_name=server_config.name, transport=transport)
        client.initialize()
        manager.register_server(client)
    return manager


def _build_mcp_manager_from_servers(servers: list[MCPServerPayload]) -> MCPClientManager:
    manager = MCPClientManager()
    for item in servers:
        transport = StdIOTransport(
            command=item.command,
            cwd=item.cwd,
            env=item.env,
        )
        client = MCPServerClient(server_name=item.name, transport=transport)
        client.initialize()
        manager.register_server(client)
    return manager


def _build_mcp_manager_for_request(request_config_path: str | None) -> MCPClientManager:
    if request_config_path and request_config_path.strip():
        return _build_mcp_manager(request_config_path.strip())

    saved = _load_mcp_config()
    inline_servers = _coerce_inline_mcp_servers(saved.servers)
    if inline_servers:
        return _build_mcp_manager_from_servers(inline_servers)

    fallback_path = saved.defaultConfigPath.strip() if saved.defaultConfigPath else ""
    if fallback_path:
        return _build_mcp_manager(fallback_path)
    return MCPClientManager()


def _test_single_mcp_server(server: MCPServerPayload) -> dict[str, Any]:
    transport = StdIOTransport(
        command=server.command,
        cwd=server.cwd,
        env=server.env,
    )
    client = MCPServerClient(server_name=server.name, transport=transport)
    started_at = perf_counter()
    try:
        init_result = client.initialize()
        tools = client.list_tools()
    finally:
        transport.close()

    return {
        "ok": True,
        "server": server.name,
        "latencyMs": int((perf_counter() - started_at) * 1000),
        "protocolVersion": init_result.get("protocolVersion"),
        "toolCount": len(tools),
        "toolNames": [str(item.get("name", "")) for item in tools if isinstance(item, dict) and item.get("name")][:20],
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/models")
def models_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "models.html")


@app.get("/mcp")
def mcp_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "mcp.html")


@app.get("/sessions")
def sessions_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "sessions.html")


@app.get("/settings")
def settings_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "settings.html")


@app.get("/quick-prompts")
def quick_prompts_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "quick-prompts.html")


@app.get("/knowledge")
def knowledge_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "knowledge.html")


@app.get("/export-import")
def export_import_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "export-import.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _mask_api_key(api_key: str) -> str:
    """对 API Key 做掩码处理，保留前3位和后4位。"""
    if not api_key or not api_key.strip():
        return ""
    key = api_key.strip()
    if len(key) <= 8:
        return "****"
    return key[:3] + "****" + key[-4:]


@app.get("/api/model-config")
def get_model_config() -> dict[str, Any]:
    config = _load_model_config()
    data = config.model_dump(mode="json")
    # 对每个 provider 的 apiKey 做掩码处理
    for provider in data.get("providers", []):
        raw_key = provider.get("apiKey", "")
        provider["apiKeyMasked"] = _mask_api_key(raw_key)
        # 不在列表接口返回完整 key
        provider.pop("apiKey", None)
        # apiKeyEnvVar 不再需要暴露给前端
        provider.pop("apiKeyEnvVar", None)
    return data


@app.get("/api/model-config/{provider_id}/reveal-key")
def reveal_provider_api_key(provider_id: str) -> dict[str, Any]:
    """按需获取 provider 的完整 API Key（前端点击查看时调用）。"""
    config = _load_model_config()
    provider = next((item for item in config.providers if item.id == provider_id), None)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"provider 不存在: {provider_id}")
    return {"ok": True, "apiKey": provider.apiKey or ""}


@app.put("/api/model-config")
def put_model_config(payload: ModelConfigPayload) -> dict[str, Any]:
    _validate_model_config(payload)
    # 合并已有的 apiKey：前端可能未传完整 key（因为 GET 已做掩码），
    # 此时需要从磁盘读取原始 key 保留
    existing_config = _load_model_config()
    existing_key_map = {p.id: p.apiKey for p in existing_config.providers}
    for provider in payload.providers:
        if not provider.apiKey and provider.id in existing_key_map:
            provider.apiKey = existing_key_map[provider.id]
    _save_model_config(payload)
    # 返回时也做掩码
    data = payload.model_dump(mode="json")
    for prov in data.get("providers", []):
        raw_key = prov.get("apiKey", "")
        prov["apiKeyMasked"] = _mask_api_key(raw_key)
        prov.pop("apiKey", None)
        prov.pop("apiKeyEnvVar", None)
    return data


@app.post("/api/model-config/discover")
def discover_models(payload: ModelDiscoverRequest) -> dict[str, Any]:
    """调用 LLM API 的 /models 端点自动发现可用模型列表"""
    base_url = payload.baseUrl.rstrip("/")
    models_url = base_url + "/models"
    headers = {"Content-Type": "application/json"}
    if payload.apiKey:
        headers["Authorization"] = f"Bearer {payload.apiKey}"

    req = request.Request(models_url, method="GET", headers=headers)
    try:
        with request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=400, detail=f"HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise HTTPException(status_code=400, detail=f"网络错误: {exc.reason}") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"解析失败: {exc}") from exc

    # 兼容 OpenAI / Anthropic / Ollama 等不同格式
    models_raw = []
    if isinstance(data, dict):
        # OpenAI 格式: { "data": [{ "id": "gpt-4", ... }] }
        raw_list = data.get("data") or data.get("models") or []
        if isinstance(raw_list, list):
            models_raw = raw_list
        # Ollama 格式: { "models": [{ "name": "llama3", ... }] }
        elif isinstance(data.get("models"), list):
            models_raw = data["models"]

    discovered: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in models_raw:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id") or item.get("name") or ""
        if not model_id or model_id in seen_ids:
            continue
        seen_ids.add(model_id)
        display_name = item.get("name") or item.get("id") or model_id
        discovered.append({
            "id": model_id,
            "name": str(display_name),
            "model": model_id,
        })

    return {"ok": True, "models": discovered, "count": len(discovered)}


@app.post("/api/model-config/test")
def test_model_connection(payload: ModelConnectionTestRequest) -> dict[str, Any]:

    config = _resolve_test_llm_config(payload)
    client = OpenAICompatibleChatClient(config)
    started_at = perf_counter()
    try:
        text = client.chat(
            [
                {
                    "role": "user",
                    "content": "健康检查：请回复一个简短 JSON 对象，例如 {\"ok\": true}。",
                }
            ],
            temperature=0.0,
        )
    except LLMClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"连接测试失败: {exc}") from exc

    duration_ms = int((perf_counter() - started_at) * 1000)
    return {
        "ok": True,
        "message": "连接测试成功",
        "latencyMs": duration_ms,
        "baseUrl": config.base_url,
        "model": config.model,
        "preview": text[:140],
    }


@app.get("/api/mcp-config")
def get_mcp_config() -> dict[str, Any]:
    return _load_mcp_config().model_dump(mode="json")


@app.put("/api/mcp-config")
def put_mcp_config(payload: MCPConfigPayload) -> dict[str, Any]:
    _coerce_inline_mcp_servers(payload.servers)
    _save_mcp_config(payload)
    return payload.model_dump(mode="json")


@app.post("/api/mcp-config/validate")
def validate_mcp_config(payload: MCPConfigValidateRequest) -> dict[str, Any]:
    config = _load_mcp_config()
    source = "inline"

    if payload.configPath and payload.configPath.strip():
        config_path = payload.configPath.strip()
        source = "file"
        path = Path(config_path)
        if not path.exists():
            raise HTTPException(status_code=400, detail=f"MCP 配置文件不存在: {path}")
        try:
            servers = load_mcp_server_configs(path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"MCP 配置解析失败: {exc}") from exc
    else:
        inline_servers = _coerce_inline_mcp_servers(config.servers)
        if inline_servers:
            servers = inline_servers
        else:
            source = "file"
            config_path = config.defaultConfigPath
            if not config_path or not config_path.strip():
                return {"ok": True, "count": 0, "servers": [], "message": "未配置 MCP server", "source": "none"}
            path = Path(config_path)
            if not path.exists():
                raise HTTPException(status_code=400, detail=f"MCP 配置文件不存在: {path}")
            try:
                servers = load_mcp_server_configs(path)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=400, detail=f"MCP 配置解析失败: {exc}") from exc

    return {
        "ok": True,
        "count": len(servers),
        "source": source,
        "servers": [
            {
                "name": item.name,
                "command": item.command,
                "cwd": item.cwd,
                "envCount": len(item.env or {}),
            }
            for item in servers
        ],
    }


@app.post("/api/mcp-config/test-server")
def test_mcp_server_connection(payload: MCPServerConnectionTestRequest) -> dict[str, Any]:
    try:
        server = MCPServerPayload.model_validate(payload.server)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"MCP server 参数非法: {exc}") from exc

    try:
        return _test_single_mcp_server(server)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"MCP server 连接测试失败: {exc}") from exc


@app.post("/api/run-react")
def run_react(payload: ReactRunRequest) -> dict:
    approval_decision = _normalize_approval_decision(payload.approvalDecision) or "1"

    rule_store = RuleStore()
    guard = PolicyGuard(input_func=lambda _: approval_decision, rule_store=rule_store)
    mcp_manager = _build_mcp_manager_for_request(payload.mcpConfig)
    router = ToolRouter(mcp_manager=mcp_manager, filesystem_allowed_dirs=payload.filesystemAllowedDirs)
    client = OpenAICompatibleChatClient(_resolve_llm_config(payload))
    agent = ReactAgent(client=client, guard=guard, router=router, max_steps=payload.maxSteps)

    started_at = perf_counter()
    try:
        result = agent.run(payload.goal)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        mcp_manager.close_all()

    duration_ms = int((perf_counter() - started_at) * 1000)
    return {
        "status": result.status,
        "finalAnswer": result.final_answer,
        "steps": result.steps,
        "durationMs": duration_ms,
    }


@app.post("/api/run-react-stream")
def run_react_stream(payload: ReactRunRequest) -> StreamingResponse:
    approval_decision = _normalize_approval_decision(payload.approvalDecision)
    run_id = str(uuid4())

    rule_store = RuleStore()
    mcp_manager = _build_mcp_manager_for_request(payload.mcpConfig)
    router = ToolRouter(mcp_manager=mcp_manager, filesystem_allowed_dirs=payload.filesystemAllowedDirs)
    client = OpenAICompatibleChatClient(_resolve_llm_config(payload))

    event_queue: Queue[dict[str, Any] | None] = Queue()
    started_at = perf_counter()

    def emit(event: dict[str, Any]) -> None:
        event_queue.put(event)

    def resolve_decision(operation: Any, prompt: str) -> str:
        if approval_decision is not None:
            return approval_decision

        approval_id = str(uuid4())
        _register_pending_approval(run_id, approval_id)
        op_dict = operation.to_dict()
        # 根据操作信息计算泛化选项
        resource = op_dict.get("resource", "")
        generalize_options = _compute_generalize_options(op_dict.get("tool", ""), resource)
        event_queue.put(
            {
                "type": "approval_required",
                "run_id": run_id,
                "approval_id": approval_id,
                "operation": op_dict,
                "prompt": prompt,
                "options": ["1", "2", "3", "4", "5", "6", "7", "y", "n"],
                "generalize_options": generalize_options,
            }
        )
        decision = _wait_pending_approval(run_id, approval_id)
        if decision is None:
            event_queue.put(
                {
                    "type": "approval_timeout",
                    "run_id": run_id,
                    "approval_id": approval_id,
                    "default_decision": "n",
                }
            )
            return "n"
        return decision

    guard = PolicyGuard(rule_store=rule_store, decision_func=resolve_decision)

    agent = ReactAgent(
        client=client,
        guard=guard,
        router=router,
        max_steps=payload.maxSteps,
        event_callback=emit,
    )

    def worker() -> None:
        try:
            result = agent.run(payload.goal)
            duration_ms = int((perf_counter() - started_at) * 1000)
            # 自动保存对话历史
            try:
                store = ConversationStore()
                store.save_conversation(
                    conversation_id=str(uuid4()),
                    goal=payload.goal,
                    status=result.status,
                    final_answer=result.final_answer,
                    steps=result.steps,
                    duration_ms=duration_ms,
                )
            except Exception:  # noqa: BLE001
                pass  # 保存失败不影响主流程
        except Exception as exc:  # noqa: BLE001
            event_queue.put({"type": "run_error", "message": str(exc)})
        finally:
            _clear_run_pending_approvals(run_id)
            mcp_manager.close_all()
            event_queue.put(None)

    event_queue.put({"type": "run_boot", "goal": payload.goal, "run_id": run_id})
    thread = Thread(target=worker, daemon=True)
    thread.start()

    def stream() -> Any:
        while True:
            event = event_queue.get()
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/api/runs/{run_id}/approvals/{approval_id}")
def submit_approval(run_id: str, approval_id: str, payload: ApprovalDecisionPayload) -> dict[str, Any]:
    decision = _normalize_approval_decision(payload.decision)
    if decision is None:
        raise HTTPException(status_code=400, detail="decision 不能为空")

    accepted = _submit_pending_approval(run_id, approval_id, decision)
    if not accepted:
        raise HTTPException(status_code=404, detail="审批请求不存在或已结束")
    return {"ok": True, "runId": run_id, "approvalId": approval_id, "decision": decision}


# ===== 对话历史 API =====


@app.get("/api/conversations")
def list_conversations(limit: int = 20, offset: int = 0) -> dict[str, Any]:
    store = ConversationStore()
    items = store.list_conversations(limit=limit, offset=offset)
    return {"ok": True, "conversations": items, "count": len(items), "total": store.count()}


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict[str, Any]:
    store = ConversationStore()
    item = store.get_conversation(conversation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="对话记录不存在")
    return {"ok": True, "conversation": item}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict[str, Any]:
    store = ConversationStore()
    if store.delete_conversation(conversation_id):
        return {"ok": True, "message": "已删除"}
    raise HTTPException(status_code=404, detail="对话记录不存在")


@app.delete("/api/conversations")
def clear_conversations() -> dict[str, Any]:
    store = ConversationStore()
    deleted = store.clear_all()
    return {"ok": True, "message": f"已清空 {deleted} 条对话记录"}


# ================== Session Management APIs =================


@app.post("/api/sessions")
def create_session(payload: CreateSessionRequest) -> dict[str, Any]:
    """创建一个新的会话"""
    store = ConversationStore()
    config_dict = payload.config.model_dump(mode="json") if payload.config else {}
    requested_name = payload.name.strip()
    session_name = requested_name or _fallback_session_name("")
    session_type = (payload.sessionType or "normal").strip().lower()
    if session_type not in {"normal", "schedule-runtime"}:
        raise HTTPException(status_code=400, detail="sessionType 仅支持 normal 或 schedule-runtime")

    session_id = store.create_session(name=session_name, config=config_dict, session_type=session_type)
    
    session = store.get_session(session_id)
    return {"ok": True, "session": session}


@app.get("/api/sessions")
def list_sessions(
    limit: int = 20,
    offset: int = 0,
    includeArchived: bool = False,
    archivedOnly: bool = False,
    includeRuntime: bool = False,
) -> dict[str, Any]:
    """列出所有会话"""
    store = ConversationStore()
    # 归档视图默认应包含运行会话，避免前端未传 includeRuntime 时看不到定时任务会话
    effective_include_runtime = includeRuntime or archivedOnly
    sessions = store.list_sessions(
        limit=limit,
        offset=offset,
        include_archived=includeArchived,
        archived_only=archivedOnly,
        include_runtime=effective_include_runtime,
    )
    return {"ok": True, "sessions": sessions}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    """获取会话详情"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True, "session": session}


@app.put("/api/sessions/{session_id}")
def update_session(session_id: str, payload: CreateSessionRequest) -> dict[str, Any]:
    """更新会话配置"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    config_dict = payload.config.model_dump(mode="json") if payload.config else session["config"]
    success = store.update_session_config(session_id, config_dict)
    if not success:
        raise HTTPException(status_code=500, detail="更新失败")
    
    updated = store.get_session(session_id)
    return {"ok": True, "session": updated}


@app.put("/api/sessions/{session_id}/name")
def rename_session(session_id: str, payload: SessionRenameRequest) -> dict[str, Any]:
    """手动重命名会话"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    normalized = _normalize_session_name(payload.name)
    if not normalized:
        raise HTTPException(status_code=400, detail="会话名称不能为空")

    if not store.update_session_name(session_id, normalized):
        raise HTTPException(status_code=500, detail="重命名失败")

    updated = store.get_session(session_id)
    return {"ok": True, "session": updated}


@app.put("/api/sessions/{session_id}/state")
def update_session_state(session_id: str, payload: SessionStateRequest) -> dict[str, Any]:
    """更新会话状态（置顶/归档）。"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    if payload.pinned is None and payload.archived is None:
        raise HTTPException(status_code=400, detail="至少提供 pinned 或 archived")

    if not store.update_session_state(
        session_id,
        pinned=payload.pinned,
        archived=payload.archived,
    ):
        raise HTTPException(status_code=500, detail="状态更新失败")

    updated = store.get_session(session_id)
    return {"ok": True, "session": updated}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, Any]:
    """删除会话及其所有任务"""
    store = ConversationStore()
    if store.delete_session(session_id):
        return {"ok": True, "message": "已删除"}
    raise HTTPException(status_code=404, detail="会话不存在")


# ================== Task Management APIs (within Session) =================


@app.post("/api/sessions/{session_id}/tasks")
def run_task_in_session(
    session_id: str,
    goal: str = Form(...),
    approvalDecision: str = Form(None),
    files: list[UploadFile] = File(default=[]),
) -> StreamingResponse:
    """在会话内发起任务（支持文件上传），返回流式结果"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    # ---- 保存上传文件并拼入文件路径上下文 ----
    import mimetypes
    uploaded_files = _save_uploaded_files(session_id, files)
    file_context_lines: list[str] = []
    image_list: list[dict[str, str]] = []  # 用于多模态 LLM 的 base64 图片列表
    _IMAGE_MIME_PREFIXES = ("image/",)

    for f_info in uploaded_files:
        size_str = f"{f_info['size']} bytes" if f_info["size"] < 1024 else f"{f_info['size'] / 1024:.1f} KB"
        mime_type = f_info.get("content_type", "") or (mimetypes.guess_type(f_info["filename"])[0] or "")

        # 图片文件：编码为 base64 直接传给多模态 LLM
        if mime_type.startswith(_IMAGE_MIME_PREFIXES):
            try:
                import base64
                img_bytes = Path(f_info["path"]).read_bytes()
                img_b64 = base64.b64encode(img_bytes).decode("ascii")
                image_list.append({"data": img_b64, "mime_type": mime_type})
                file_context_lines.append(f"- 图片: {f_info['filename']}, 大小: {size_str}（已直接发送给视觉模型）")
            except Exception:
                file_context_lines.append(f"- 文件名: {f_info['filename']}, 大小: {size_str}, 路径: {f_info['path']}")
        else:
            file_context_lines.append(f"- 文件名: {f_info['filename']}, 大小: {size_str}, 路径: {f_info['path']}")

    file_context = ""
    if file_context_lines:
        file_context = (
            "\n用户上传了以下文件（你可以使用 filesystem.read_file 读取它们的路径来查看内容）：\n"
            + "\n".join(file_context_lines) + "\n\n"
        )

    # 构造会话问答上下文，让任务在连续对话中完成
    # 排除 interrupted 状态的任务（后端重启导致的假失败，不是真实的对话历史）
    recent_tasks = store.list_tasks(session_id=session_id, limit=10, offset=0)
    valid_tasks = [t for t in recent_tasks if t.get("status") not in ("interrupted",)]
    conversation_lines: list[str] = []
    for item in reversed(valid_tasks[-6:]):
        item_goal = str(item.get("goal", "")).strip()
        answer = str(item.get("final_answer", "")).strip()
        status = str(item.get("status", "")).strip()
        if item_goal:
            conversation_lines.append(f"用户: {item_goal}")
        if answer:
            conversation_lines.append(f"助手: {answer}")
        elif status:
            conversation_lines.append(f"助手: [status={status}]")

    contextual_goal = file_context + goal
    if conversation_lines:
        history_block = "\n".join(conversation_lines)
        contextual_goal = (
            file_context
            + "你正在一个持续会话里工作。请基于以下历史问答继续完成用户新问题。\n\n"
            f"历史问答:\n{history_block}\n\n"
            f"用户新问题: {goal}"
        )

    # 定时任务会话：附带定时任务列表上下文和角色声明
    if session.get("session_type") == "schedule-runtime":
        schedule_context = _build_schedule_management_context(store, session_id)
        if schedule_context:
            contextual_goal = schedule_context + "\n\n" + contextual_goal

    # 从会话配置中恢复 ReactRunRequest
    session_config = session.get("config", {})
    run_request = ReactRunRequest(
        goal=contextual_goal,
        providerId=session_config.get("providerId"),
        modelId=session_config.get("modelId"),
        llmBaseUrl=session_config.get("llmBaseUrl"),
        llmApiKey=session_config.get("llmApiKey"),
        llmModel=session_config.get("llmModel"),
        llmTimeout=session_config.get("llmTimeout"),
        maxSteps=session_config.get("maxSteps", 50),
        approvalDecision=approvalDecision,
        mcpConfig=session_config.get("mcpConfig"),
        jsonMode=session_config.get("jsonMode"),
        filesystemAllowedDirs=session_config.get("filesystemAllowedDirs"),
    )
    
    # 创建任务记录
    task_id = store.create_task(session_id=session_id, goal=goal)

    def rename_session_async() -> None:
        """异步生成问题摘要并更新会话名称，避免阻塞任务执行。
        
        仅在首次提问时自动命名；已有历史任务说明名称已生成或用户已手动命名，不再覆盖。
        """
        rename_goal = goal.strip()
        if not rename_goal:
            return

        try:
            # 当前任务已被 create_task 写入，count > 1 说明不是首次提问，跳过
            task_rows = store.list_tasks(session_id=session_id, limit=2, offset=0)
            if len(task_rows) > 1:
                return

            config_payload: SessionConfigPayload | None = None
            if isinstance(session_config, dict):
                config_payload = SessionConfigPayload.model_validate(session_config)
            summarized = _generate_session_name(goal, config_payload)
            normalized = _normalize_session_name(summarized)
            if not normalized:
                return

            latest = store.get_session(session_id)
            if latest and latest.get("name") == normalized:
                return

            if store.update_session_name(session_id, normalized):
                emit(
                    {
                        "type": "session_renamed",
                        "session_id": session_id,
                        "name": normalized,
                    }
                )
        except Exception:  # noqa: BLE001
            return

    # 复用现有的 run-react-stream 逻辑，但保存为 task
    run_id = f"session-{session_id}-task-{task_id}"
    event_queue: Queue[dict[str, Any] | None] = Queue()
    started_at = perf_counter()
    event_records: list[dict[str, Any]] = []
    event_seq = 0

    def emit(event: dict[str, Any]) -> None:
        nonlocal event_seq
        event_seq += 1
        enriched = {
            **event,
            "event_seq": event_seq,
            "event_at": datetime.now().isoformat(timespec="milliseconds"),
        }
        event_records.append(enriched)
        event_queue.put(enriched)

        # 实时保存步骤到 DB，确保刷新页面后仍可查看
        if event.get("type") == "step_complete" and event.get("step_record"):
            try:
                store.append_task_step(task_id, event["step_record"])
            except Exception:  # noqa: BLE001
                pass  # 保存失败不阻塞主流程

        # 将 approval_required 事件也追加到 task events，便于页面刷新后恢复审批卡片
        if event.get("type") == "approval_required":
            try:
                store.append_task_step(task_id, {"type": "approval_required_persisted", "approval_event": enriched})
            except Exception:  # noqa: BLE001
                pass

    Thread(target=rename_session_async, daemon=True).start()

    def resolve_decision(operation: Any, prompt: str) -> str:
        preset_decision = _normalize_approval_decision(run_request.approvalDecision)
        if preset_decision is not None:
            return preset_decision

        approval_id = str(uuid4())
        _register_pending_approval(run_id, approval_id)
        op_dict = operation.to_dict()
        resource = op_dict.get("resource", "")
        generalize_options = _compute_generalize_options(op_dict.get("tool", ""), resource)
        emit(
            {
                "type": "approval_required",
                "run_id": run_id,
                "approval_id": approval_id,
                "operation": op_dict,
                "prompt": prompt,
                "options": ["1", "2", "3", "4", "5", "6", "7", "y", "n"],
                "generalize_options": generalize_options,
                "session_id": session_id,
            }
        )
        decision = _wait_pending_approval(run_id, approval_id, timeout_sec=300.0)
        if decision is None:
            emit(
                {
                    "type": "approval_timeout",
                    "run_id": run_id,
                    "approval_id": approval_id,
                    "default_decision": "n",
                    "session_id": session_id,
                }
            )
            return "n"
        return decision

    rule_store = RuleStore()
    conv_store = ConversationStore()
    guard = PolicyGuard(
        rule_store=rule_store,
        conversation_store=conv_store,
        session_id=session_id,
        decision_func=resolve_decision,
    )

    llm_config = _resolve_llm_config(run_request)
    client = OpenAICompatibleChatClient(llm_config)
    mcp_manager = _build_mcp_manager_for_request(run_request.mcpConfig)
    router = ToolRouter(
        mcp_manager=mcp_manager,
        filesystem_allowed_dirs=run_request.filesystemAllowedDirs,
        session_id=session_id,
    )

    agent = ReactAgent(
        client=client,
        guard=guard,
        router=router,
        max_steps=run_request.maxSteps,
        event_callback=emit,
    )

    def worker() -> None:
        try:
            result = agent.run(
                run_request.goal,
                images=image_list if image_list else None,
            )
            duration_ms = int((perf_counter() - started_at) * 1000)
            # 保存任务结果到数据库
            try:
                store.save_task(
                    task_id=task_id,
                    status=result.status,
                    final_answer=result.final_answer,
                    steps=result.steps,
                    events=event_records,
                    duration_ms=duration_ms,
                )
            except Exception:  # noqa: BLE001
                pass  # 保存失败不影响主流程
        except Exception as exc:  # noqa: BLE001
            emit({"type": "run_error", "message": str(exc), "session_id": session_id})

            # 失败也要尽量落库存档，便于历史回放完整事件。
            try:
                duration_ms = int((perf_counter() - started_at) * 1000)
                store.save_task(
                    task_id=task_id,
                    status="error",
                    final_answer=f"任务执行异常：{exc}",
                    steps=[],
                    events=event_records,
                    duration_ms=duration_ms,
                )
            except Exception:  # noqa: BLE001
                pass
        finally:
            _clear_run_pending_approvals(run_id)
            mcp_manager.close_all()
            event_queue.put(None)

    emit({"type": "run_boot", "goal": run_request.goal, "run_id": run_id, "task_id": task_id, "session_id": session_id})
    thread = Thread(target=worker, daemon=True)
    thread.start()

    def stream() -> Any:
        while True:
            event = event_queue.get()
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.get("/api/sessions/{session_id}/tasks")
def list_session_tasks(session_id: str, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """列出会话内的所有任务"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    tasks = store.list_tasks(session_id=session_id, limit=limit, offset=offset)
    return {"ok": True, "tasks": tasks}


@app.post("/api/sessions/{session_id}/schedules")
def create_session_schedule(session_id: str, payload: ScheduledTaskCreateRequest) -> dict[str, Any]:
    """在会话中创建定时任务。"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    name = payload.name.strip()
    prompt = payload.prompt.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 不能为空")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")

    schedule_id = store.create_scheduled_task(
        session_id=session_id,
        name=name,
        prompt=prompt,
        interval_seconds=payload.intervalSeconds,
        enabled=payload.enabled,
    )
    schedule = store.get_scheduled_task(schedule_id)

    # 异步重新生成会话摘要名称
    Thread(target=_regenerate_schedule_session_name, args=(session_id,), daemon=True).start()

    return {"ok": True, "schedule": schedule}


@app.get("/api/sessions/{session_id}/schedules")
def list_session_schedules(session_id: str, includeDisabled: bool = True) -> dict[str, Any]:
    """列出会话内定时任务。"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    schedules = store.list_scheduled_tasks(session_id=session_id, include_disabled=includeDisabled)
    return {"ok": True, "schedules": schedules, "count": len(schedules)}


@app.get("/api/sessions/{session_id}/schedules/{schedule_id}")
def get_session_schedule(session_id: str, schedule_id: str) -> dict[str, Any]:
    """获取会话内单个定时任务。"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    schedule = store.get_scheduled_task(schedule_id)
    if schedule is None or schedule.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    return {"ok": True, "schedule": schedule}


@app.put("/api/sessions/{session_id}/schedules/{schedule_id}")
def update_session_schedule(
    session_id: str,
    schedule_id: str,
    payload: ScheduledTaskUpdateRequest,
) -> dict[str, Any]:
    """更新会话内定时任务（计划/提示词/状态）。"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    current = store.get_scheduled_task(schedule_id)
    if current is None or current.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail="定时任务不存在")

    if (
        payload.name is None
        and payload.prompt is None
        and payload.intervalSeconds is None
        and payload.enabled is None
    ):
        raise HTTPException(status_code=400, detail="至少提供一个可更新字段")

    normalized_name = payload.name.strip() if payload.name is not None else None
    normalized_prompt = payload.prompt.strip() if payload.prompt is not None else None
    if payload.name is not None and not normalized_name:
        raise HTTPException(status_code=400, detail="name 不能为空")
    if payload.prompt is not None and not normalized_prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")

    success = store.update_scheduled_task(
        schedule_id=schedule_id,
        name=normalized_name,
        prompt=normalized_prompt,
        interval_seconds=payload.intervalSeconds,
        enabled=payload.enabled,
    )
    if not success:
        raise HTTPException(status_code=500, detail="更新失败")

    schedule = store.get_scheduled_task(schedule_id)

    # 异步重新生成会话摘要名称
    Thread(target=_regenerate_schedule_session_name, args=(session_id,), daemon=True).start()

    return {"ok": True, "schedule": schedule}


@app.delete("/api/sessions/{session_id}/schedules/{schedule_id}")
def delete_session_schedule(session_id: str, schedule_id: str) -> dict[str, Any]:
    """删除会话内定时任务。"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    schedule = store.get_scheduled_task(schedule_id)
    if schedule is None or schedule.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail="定时任务不存在")

    if not store.delete_scheduled_task(schedule_id):
        raise HTTPException(status_code=500, detail="删除失败")

    # 异步重新生成会话摘要名称
    Thread(target=_regenerate_schedule_session_name, args=(session_id,), daemon=True).start()

    return {"ok": True, "message": "已删除"}


@app.post("/api/sessions/{session_id}/schedules/{schedule_id}/run-now")
def run_session_schedule_now(session_id: str, schedule_id: str) -> dict[str, Any]:
    """手动立即触发一次定时任务。"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    schedule = store.get_scheduled_task(schedule_id)
    if schedule is None or schedule.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    if not schedule.get("enabled", True):
        raise HTTPException(status_code=400, detail="定时任务已禁用，无法手动执行")

    target = store.claim_scheduled_task(schedule_id)
    if target is None:
        raise HTTPException(status_code=409, detail="定时任务正在执行中")

    Thread(target=_run_scheduled_task_once, args=(target, "manual"), daemon=True).start()
    return {"ok": True, "message": "已触发执行"}


@app.get("/api/sessions/{session_id}/schedules/{schedule_id}/runs")
def list_session_schedule_runs(
    session_id: str,
    schedule_id: str,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """列出会话内某个定时任务的执行记录。"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    schedule = store.get_scheduled_task(schedule_id)
    if schedule is None or schedule.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail="定时任务不存在")

    rows = store.list_scheduled_task_runs(schedule_id=schedule_id, limit=limit, offset=offset)
    return {"ok": True, "runs": rows, "count": len(rows)}


@app.get("/api/sessions/{session_id}/approvals/pending")
def list_session_pending_approvals(session_id: str) -> dict[str, Any]:
    """列出会话内当前仍在等待用户决策的审批项。"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    approvals = _list_pending_approvals_for_session(session_id)
    return {"ok": True, "session_id": session_id, "approvals": approvals, "count": len(approvals)}


# ================== Tools & Policy Rules APIs =================


@app.get("/api/tools")
def list_tools(session_id: str | None = None) -> dict[str, Any]:
    """返回当前所有可用工具及其动作列表。"""
    mcp_manager = _build_mcp_manager_for_request(None)
    router = ToolRouter(
        mcp_manager=mcp_manager,
        session_id=session_id,
    )
    try:
        tools = router.list_tools()
    except Exception:  # noqa: BLE001
        tools = []
    finally:
        mcp_manager.close_all()
    return {"ok": True, "tools": tools, "count": len(tools)}


@app.get("/api/policy/rules")
def list_global_rules() -> dict[str, Any]:
    """列出所有全局持久规则。"""
    store = RuleStore()
    rules = store.list_rules()
    return {
        "ok": True,
        "rules": [
            {
                "id": r.id,
                "tool": r.tool,
                "action": r.action,
                "resource": r.resource,
                "effect": r.effect,
                "created_at": r.created_at,
                "expires_at": r.expires_at,
                "max_risk": r.max_risk,
            }
            for r in rules
        ],
        "count": len(rules),
    }


@app.delete("/api/policy/rules/{rule_id}")
def delete_global_rule(rule_id: str) -> dict[str, Any]:
    """删除一条全局持久规则。"""
    store = RuleStore()
    if store.delete_rule(rule_id):
        return {"ok": True, "message": "已删除"}
    raise HTTPException(status_code=404, detail="规则不存在")


class SessionRuleCreateRequest(BaseModel):
    tool: str = Field(min_length=1)
    action: str = Field(min_length=1)
    resource: str = Field(min_length=1)
    effect: str = Field(min_length=1)


@app.get("/api/sessions/{session_id}/policy/rules")
def list_session_rules(session_id: str) -> dict[str, Any]:
    """列出会话级策略规则。"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    rules = store.list_session_rules(session_id)
    return {"ok": True, "rules": rules, "count": len(rules)}


@app.post("/api/sessions/{session_id}/policy/rules")
def create_session_rule(session_id: str, payload: SessionRuleCreateRequest) -> dict[str, Any]:
    """创建会话级策略规则。"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    if payload.effect not in ("allow", "deny"):
        raise HTTPException(status_code=400, detail="effect 必须是 allow 或 deny")

    rule_id = store.create_session_rule(
        session_id=session_id,
        tool=payload.tool,
        action=payload.action,
        resource=payload.resource,
        effect=payload.effect,
    )
    rule = store.get_session_rule(rule_id)
    return {"ok": True, "rule": rule}


@app.delete("/api/sessions/{session_id}/policy/rules/{rule_id}")
def delete_session_rule(session_id: str, rule_id: str) -> dict[str, Any]:
    """删除一条会话级策略规则。"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    rule = store.get_session_rule(rule_id)
    if rule is None or rule.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail="规则不存在")

    if store.delete_session_rule(rule_id):
        return {"ok": True, "message": "已删除"}
    raise HTTPException(status_code=500, detail="删除失败")


# ================== Config Export / Import APIs =================


class ConfigExportRequest(BaseModel):
    """配置导出请求：选择要导出的模块"""
    exportModels: bool = True
    exportMcp: bool = True


class ConfigImportRequest(BaseModel):
    """配置导入请求"""
    payload: dict[str, Any]
    importModels: bool = True
    importMcp: bool = True


@app.post("/api/config/export")
def export_config(payload: ConfigExportRequest) -> dict[str, Any]:
    """导出模型和/或 MCP 配置，生成可导入的 JSON 数据包"""
    result: dict[str, Any] = {
        "version": "1.0",
        "exportedAt": _now_iso_seconds(),
    }

    if payload.exportModels:
        config = _load_model_config()
        result["models"] = config.model_dump(mode="json")

    if payload.exportMcp:
        config = _load_mcp_config()
        result["mcp"] = config.model_dump(mode="json")

    return {"ok": True, "data": result}


@app.post("/api/config/import")
def import_config(payload: ConfigImportRequest) -> dict[str, Any]:
    """导入模型和/或 MCP 配置。会覆盖对应模块的现有配置。"""
    data = payload.payload
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="payload 必须是 JSON 对象")

    version = data.get("version")
    if version != "1.0":
        raise HTTPException(status_code=400, detail=f"不支持的配置版本: {version}")

    results: dict[str, Any] = {"imported": []}

    if payload.importModels:
        models_data = data.get("models")
        if models_data is None:
            results["models"] = {"skipped": True, "reason": "导出数据中不包含模型配置"}
        else:
            try:
                models_config = ModelConfigPayload.model_validate(models_data)
                _validate_model_config(models_config)
                # 合并已有 apiKey：如果导入数据中 apiKey 为空，保留本地已有的
                existing_config = _load_model_config()
                existing_key_map = {p.id: p.apiKey for p in existing_config.providers}
                for provider in models_config.providers:
                    if not provider.apiKey and provider.id in existing_key_map:
                        provider.apiKey = existing_key_map[provider.id]
                _save_model_config(models_config)
                results["models"] = {"ok": True}
                results["imported"].append("models")
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"模型配置导入失败: {exc}") from exc

    if payload.importMcp:
        mcp_data = data.get("mcp")
        if mcp_data is None:
            results["mcp"] = {"skipped": True, "reason": "导出数据中不包含 MCP 配置"}
        else:
            try:
                mcp_config = MCPConfigPayload.model_validate(mcp_data)
                _coerce_inline_mcp_servers(mcp_config.servers)
                _save_mcp_config(mcp_config)
                results["mcp"] = {"ok": True}
                results["imported"].append("mcp")
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"MCP 配置导入失败: {exc}") from exc

    return {"ok": True, **results}


@app.get("/api/sessions/{session_id}/tasks/{task_id}")
def get_session_task(session_id: str, task_id: str) -> dict[str, Any]:
    """获取会话内任务的详情"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    task = store.get_task(task_id)
    if task is None or task.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return {"ok": True, "task": task}


# ==================== 知识库 API ====================

# 知识库依赖 numpy，打包环境中可能缺失，使用延迟导入


class KnowledgeAddTextRequest(BaseModel):
    """添加文本到知识库"""
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    tags: list[str] | None = None


class KnowledgeSearchRequest(BaseModel):
    """搜索知识库"""
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class EmbeddingConfigRequest(BaseModel):
    """嵌入模型配置"""
    provider: str = "openai_compatible"
    baseUrl: str = ""
    apiKey: str = ""
    model: str = "text-embedding-3-small"
    dimension: int = 1536
    timeout: float = Field(default=30.0, ge=1.0, le=120.0)


def _get_knowledge_store():
    """获取知识库实例（使用配置的嵌入模型或 Mock）。延迟导入以避免 numpy 缺失导致启动失败。"""
    try:
        from backend.memory.knowledge_store import KnowledgeStore  # noqa: PLC0415
        from backend.memory.embedding import (  # noqa: PLC0415
            create_embedding_provider,
            load_embedding_config,
        )
    except ImportError:
        raise HTTPException(status_code=503, detail="知识库功能不可用（缺少 numpy 依赖）")

    try:
        config = load_embedding_config()
        if config.provider == "mock" or not config.base_url or not config.api_key:
            return KnowledgeStore()
        provider = create_embedding_provider(config)
        return KnowledgeStore(embedding_provider=provider)
    except Exception:
        return KnowledgeStore()


@app.get("/api/knowledge/documents")
def api_knowledge_list_docs(limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """列出知识库文档。"""
    store = _get_knowledge_store()
    docs = store.list_documents(limit=limit, offset=offset)
    total = store.count_documents()
    return {"ok": True, "documents": docs, "total": total}


@app.get("/api/knowledge/documents/{doc_id}")
def api_knowledge_get_doc(doc_id: str) -> dict[str, Any]:
    """获取知识库文档详情。"""
    store = _get_knowledge_store()
    doc = store.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"ok": True, "document": doc}


@app.post("/api/knowledge/documents")
def api_knowledge_add_doc(payload: KnowledgeAddTextRequest) -> dict[str, Any]:
    """添加文本文档到知识库。"""
    store = _get_knowledge_store()
    doc_id = store.add_document(
        title=payload.title.strip(),
        content=payload.content.strip(),
        source_type="text",
        tags=payload.tags,
    )
    doc = store.get_document(doc_id)
    return {
        "ok": True,
        "document_id": doc_id,
        "title": payload.title.strip(),
        "char_count": doc["char_count"] if doc else len(payload.content),
    }


@app.post("/api/knowledge/documents/upload")
async def api_knowledge_upload_doc(
    title: str = Form(...),
    file: UploadFile = File(...),
    tags: str = Form(default="[]"),
) -> dict[str, Any]:
    """上传文件到知识库（支持 .txt/.md/.json/.csv 等文本文件）。"""
    # 读取文件内容
    content = await file.read()
    text = content.decode("utf-8", errors="replace")

    if not text.strip():
        raise HTTPException(status_code=400, detail="文件内容为空")

    try:
        tags_list = json.loads(tags)
        if not isinstance(tags_list, list):
            tags_list = []
    except json.JSONDecodeError:
        tags_list = []

    store = _get_knowledge_store()
    doc_id = store.add_document(
        title=title.strip() or (file.filename or "未命名文件"),
        content=text.strip(),
        source_type="file",
        source_name=file.filename,
        tags=tags_list,
    )
    doc = store.get_document(doc_id)
    return {
        "ok": True,
        "document_id": doc_id,
        "title": title.strip() or file.filename,
        "source_name": file.filename,
        "char_count": doc["char_count"] if doc else len(text),
    }


@app.delete("/api/knowledge/documents/{doc_id}")
def api_knowledge_delete_doc(doc_id: str) -> dict[str, Any]:
    """删除知识库文档。"""
    store = _get_knowledge_store()
    deleted = store.delete_document(doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"ok": True, "deleted_document_id": doc_id}


@app.post("/api/knowledge/search")
def api_knowledge_search(payload: KnowledgeSearchRequest) -> dict[str, Any]:
    """搜索知识库。"""
    store = _get_knowledge_store()
    results = store.search(query=payload.query.strip(), top_k=payload.top_k)
    return {"ok": True, "query": payload.query.strip(), "results": results, "total": len(results)}


@app.get("/api/knowledge/embedding-config")
def api_knowledge_get_embedding_config() -> dict[str, Any]:
    """获取当前嵌入模型配置。"""
    try:
        from backend.memory.embedding import load_embedding_config  # noqa: PLC0415
    except ImportError:
        raise HTTPException(status_code=503, detail="知识库功能不可用（缺少 numpy 依赖）")
    config = load_embedding_config()
    return {"ok": True, "config": config.to_dict()}


@app.post("/api/knowledge/embedding-config")
def api_knowledge_save_embedding_config(payload: EmbeddingConfigRequest) -> dict[str, Any]:
    """保存嵌入模型配置。"""
    try:
        from backend.memory.embedding import (  # noqa: PLC0415
            EmbeddingConfig,
            create_embedding_provider,
            save_embedding_config,
        )
    except ImportError:
        raise HTTPException(status_code=503, detail="知识库功能不可用（缺少 numpy 依赖）")

    config = EmbeddingConfig(
        provider=payload.provider,
        base_url=payload.baseUrl,
        api_key=payload.apiKey,
        model=payload.model,
        dimension=payload.dimension,
        timeout=payload.timeout,
    )

    # 验证配置是否可用（非 mock 模式时）
    if config.provider != "mock" and config.base_url and config.api_key:
        try:
            provider = create_embedding_provider(config)
            provider.embed("test")
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"嵌入模型配置验证失败: {exc}",
            ) from exc

    save_embedding_config(config)
    return {"ok": True}


@app.post("/api/knowledge/rebuild-index")
def api_knowledge_rebuild_index() -> dict[str, Any]:
    """重建知识库索引（FTS + 向量嵌入）。"""
    store = _get_knowledge_store()
    fts_count = store.rebuild_all_fts()
    embed_count = store.regenerate_embeddings()
    return {"ok": True, "fts_chunks": fts_count, "embedded_chunks": embed_count}
