from __future__ import annotations

import json
import os
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
from pydantic import BaseModel, Field

from backend.agent import ReactAgent
from backend.llm import OpenAICompatibleChatClient, OpenAICompatibleConfig, LLMClientError
from backend.mcp import MCPClientManager, MCPServerClient, StdIOTransport, load_mcp_server_configs
from backend.memory.rule_store import RuleStore
from backend.memory.conversation_store import ConversationStore
from backend.policy_guard.guard import PolicyGuard
from backend.tool_router.router import ToolRouter

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "ui" / "web"

app = FastAPI(title="MyClaw Web UI", version="0.2.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ReactRunRequest(BaseModel):
    goal: str = Field(min_length=1)
    providerId: str | None = None
    modelId: str | None = None
    llmBaseUrl: str | None = None
    llmApiKey: str | None = None
    llmModel: str | None = None
    llmTimeout: float | None = Field(default=None, ge=1.0, le=300.0)
    maxSteps: int = Field(default=8, ge=1, le=30)
    approvalDecision: str | None = None
    mcpConfig: str | None = None
    jsonMode: bool | None = None
    filesystemAllowedDirs: list[str] | None = None


class ProviderModel(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    model: str = Field(min_length=1)


class ModelProvider(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    baseUrl: str = Field(min_length=1)
    apiKeyEnvVar: str = ""  # 环境变量名，不再存明文
    apiKey: str = ""  # 前端传入的明文 API Key，保存时自动写入 .env，不持久化到 JSON
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


MODEL_CONFIG_PATH = ROOT / "data" / "model_profiles.json"
ENV_FILE_PATH = ROOT / ".env"

ALLOWED_APPROVAL_DECISIONS = {"1", "2", "3", "4", "y", "n"}


@dataclass(slots=True)
class PendingApproval:
    event: Event
    decision: str | None = None


_approval_lock = Lock()
_pending_approvals: dict[tuple[str, str], PendingApproval] = {}


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


def _default_model_config() -> ModelConfigPayload:
    return ModelConfigPayload(
        defaultProviderId="openai-local",
        defaultModelId="gpt-4.1-mini",
        providers=[
            ModelProvider(
                id="openai-local",
                name="Local Default",
                baseUrl="http://localhost:8000/v1",
                apiKeyEnvVar="MYCLAW_LLM_API_KEY",
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
    """优先使用内联 key，其次环境变量，最后空字符串"""
    if inline_key:
        return inline_key
    if provider.apiKeyEnvVar:
        return os.getenv(provider.apiKeyEnvVar, "")
    return ""


def _load_model_config() -> ModelConfigPayload:
    if not MODEL_CONFIG_PATH.exists():
        return _default_model_config()

    try:
        payload = json.loads(MODEL_CONFIG_PATH.read_text(encoding="utf-8"))
        return ModelConfigPayload.model_validate(payload)
    except Exception:  # noqa: BLE001
        return _default_model_config()


def _save_api_keys_to_env(providers: list[ModelProvider]) -> None:
    """将 provider 的 API Key 写入 .env 文件，JSON 中只存环境变量引用名。"""
    if not ENV_FILE_PATH.exists():
        ENV_FILE_PATH.write_text("", encoding="utf-8")

    lines = ENV_FILE_PATH.read_text(encoding="utf-8").splitlines(keepends=False)
    # 解析现有 .env 为字典
    env_map: dict[str, str] = {}
    remaining_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            remaining_lines.append(line)
            continue
        if "=" in stripped:
            key, _, val = stripped.partition("=")
            env_map[key.strip()] = val.strip()
        else:
            remaining_lines.append(line)

    # 更新或新增 API Key
    for provider in providers:
        if not provider.apiKey:
            continue
        env_var_name = f"MYCLAW_API_KEY_{provider.id.upper().replace('-', '_')}"
        env_map[env_var_name] = provider.apiKey
        provider.apiKeyEnvVar = env_var_name
        provider.apiKey = ""  # 清除明文，不持久化到 JSON

    # 写回 .env
    output_lines = list(remaining_lines)
    for key, val in env_map.items():
        output_lines.append(f"{key}={val}")
    ENV_FILE_PATH.write_text("\n".join(output_lines) + "\n", encoding="utf-8")


def _save_model_config(config: ModelConfigPayload) -> None:
    MODEL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_CONFIG_PATH.write_text(
        json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
    if payload.llmBaseUrl and payload.llmApiKey is not None and payload.llmModel:
        return OpenAICompatibleConfig(
            base_url=payload.llmBaseUrl,
            api_key=payload.llmApiKey,
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
        raise HTTPException(status_code=400, detail=f"provider {provider.id} 下不存在 model: {model_id}")

    api_key = _resolve_api_key(provider, payload.llmApiKey or "")
    return OpenAICompatibleConfig(
        base_url=provider.baseUrl,
        api_key=api_key,
        model=selected_model.model,
        timeout=payload.llmTimeout or provider.timeout,
        json_mode=provider.jsonMode if payload.jsonMode is None else payload.jsonMode,
    )


def _resolve_test_llm_config(payload: ModelConnectionTestRequest) -> OpenAICompatibleConfig:
    if payload.baseUrl and payload.model:
        return OpenAICompatibleConfig(
            base_url=payload.baseUrl,
            api_key=payload.apiKey,
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
        raise HTTPException(status_code=400, detail=f"provider {provider.id} 下不存在可测试 model")

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
    if not config_path:
        return manager

    for server_config in load_mcp_server_configs(config_path):
        transport = StdIOTransport(
            command=server_config.command,
            cwd=server_config.cwd,
            env=server_config.env,
        )
        client = MCPServerClient(server_name=server_config.name, transport=transport)
        client.initialize()
        manager.register_server(client)
    return manager


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/models")
def models_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "models.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/model-config")
def get_model_config() -> dict[str, Any]:
    config = _load_model_config()
    return config.model_dump(mode="json")


@app.put("/api/model-config")
def put_model_config(payload: ModelConfigPayload) -> dict[str, Any]:
    _validate_model_config(payload)
    _save_api_keys_to_env(payload.providers)
    _save_model_config(payload)
    return payload.model_dump(mode="json")


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


@app.post("/api/run-react")
def run_react(payload: ReactRunRequest) -> dict:
    approval_decision = _normalize_approval_decision(payload.approvalDecision) or "1"

    rule_store = RuleStore()
    guard = PolicyGuard(input_func=lambda _: approval_decision, rule_store=rule_store)
    mcp_manager = _build_mcp_manager(payload.mcpConfig)
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
    mcp_manager = _build_mcp_manager(payload.mcpConfig)
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
        event_queue.put(
            {
                "type": "approval_required",
                "run_id": run_id,
                "approval_id": approval_id,
                "operation": operation.to_dict(),
                "prompt": prompt,
                "options": ["1", "2", "3", "4", "n"],
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
