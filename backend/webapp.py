from __future__ import annotations

import json
from datetime import datetime
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


# ================= Session API Models =================

class SessionConfigPayload(BaseModel):
    """会话配置"""
    providerId: str | None = None
    modelId: str | None = None
    llmBaseUrl: str | None = None
    llmApiKey: str | None = None
    llmModel: str | None = None
    llmTimeout: float | None = Field(default=None, ge=1.0, le=300.0)
    maxSteps: int = Field(default=8, ge=1, le=30)
    mcpConfig: str | None = None
    mcpServers: list[dict[str, Any]] | None = None
    jsonMode: bool | None = None
    filesystemAllowedDirs: list[str] | None = None


class CreateSessionRequest(BaseModel):
    """创建会话请求"""
    name: str = ""
    seedGoal: str = ""
    config: SessionConfigPayload | None = None


class SessionRenameRequest(BaseModel):
    """会话重命名请求"""
    name: str = Field(min_length=1)


class SessionTaskRequest(BaseModel):
    """在会话内发起任务请求"""
    goal: str = Field(min_length=1)
    approvalDecision: str | None = None


class ProviderModel(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    model: str = Field(min_length=1)


class ModelProvider(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    baseUrl: str = Field(min_length=1)
    apiKeyEnvVar: str = ""  # 兼容旧字段，当前不再参与解析
    apiKey: str = ""  # 直接持久化的明文 API Key
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


MODEL_CONFIG_PATH = ROOT / "data" / "model_profiles.json"
MCP_CONFIG_PATH = ROOT / "data" / "mcp_config.json"

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
        llm_config = _resolve_session_llm_config(config)
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


@app.get("/settings")
def settings_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "settings.html")


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


# ================== Session Management APIs =================


@app.post("/api/sessions")
def create_session(payload: CreateSessionRequest) -> dict[str, Any]:
    """创建一个新的会话"""
    store = ConversationStore()
    config_dict = payload.config.model_dump(mode="json") if payload.config else {}
    requested_name = payload.name.strip()
    session_name = requested_name or _fallback_session_name("")
    session_id = store.create_session(name=session_name, config=config_dict)
    
    session = store.get_session(session_id)
    return {"ok": True, "session": session}


@app.get("/api/sessions")
def list_sessions(limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """列出所有会话"""
    store = ConversationStore()
    sessions = store.list_sessions(limit=limit, offset=offset)
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


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, Any]:
    """删除会话及其所有任务"""
    store = ConversationStore()
    if store.delete_session(session_id):
        return {"ok": True, "message": "已删除"}
    raise HTTPException(status_code=404, detail="会话不存在")


# ================== Task Management APIs (within Session) =================


@app.post("/api/sessions/{session_id}/tasks")
def run_task_in_session(session_id: str, payload: SessionTaskRequest) -> StreamingResponse:
    """在会话内发起任务，返回流式结果"""
    store = ConversationStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 构造会话问答上下文，让任务在连续对话中完成
    recent_tasks = store.list_tasks(session_id=session_id, limit=6, offset=0)
    conversation_lines: list[str] = []
    for item in reversed(recent_tasks):
        goal = str(item.get("goal", "")).strip()
        answer = str(item.get("final_answer", "")).strip()
        status = str(item.get("status", "")).strip()
        if goal:
            conversation_lines.append(f"用户: {goal}")
        if answer:
            conversation_lines.append(f"助手: {answer}")
        elif status:
            conversation_lines.append(f"助手: [status={status}]")

    contextual_goal = payload.goal
    if conversation_lines:
        history_block = "\n".join(conversation_lines)
        contextual_goal = (
            "你正在一个持续会话里工作。请基于以下历史问答继续完成用户新问题。\n\n"
            f"历史问答:\n{history_block}\n\n"
            f"用户新问题: {payload.goal}"
        )
    
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
        maxSteps=session_config.get("maxSteps", 8),
        approvalDecision=payload.approvalDecision,
        mcpConfig=session_config.get("mcpConfig"),
        jsonMode=session_config.get("jsonMode"),
        filesystemAllowedDirs=session_config.get("filesystemAllowedDirs"),
    )
    
    # 创建任务记录
    task_id = store.create_task(session_id=session_id, goal=payload.goal)

    def rename_session_async() -> None:
        """异步生成问题摘要并更新会话名称，避免阻塞任务执行。"""
        goal = payload.goal.strip()
        if not goal:
            return

        try:
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
                event_queue.put(
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

    Thread(target=rename_session_async, daemon=True).start()

    def resolve_decision(operation: Any, prompt: str) -> str:
        preset_decision = _normalize_approval_decision(run_request.approvalDecision)
        if preset_decision is not None:
            return preset_decision

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
        decision = _wait_pending_approval(run_id, approval_id, timeout_sec=300.0)
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

    rule_store = RuleStore()
    guard = PolicyGuard(rule_store=rule_store, decision_func=resolve_decision)

    llm_config = _resolve_llm_config(run_request)
    client = OpenAICompatibleChatClient(llm_config)
    mcp_manager = _build_mcp_manager_for_request(run_request.mcpConfig)
    router = ToolRouter(mcp_manager=mcp_manager, filesystem_allowed_dirs=run_request.filesystemAllowedDirs)

    def emit(event: dict[str, Any]) -> None:
        event_queue.put(event)

    agent = ReactAgent(
        client=client,
        guard=guard,
        router=router,
        max_steps=run_request.maxSteps,
        event_callback=emit,
    )

    def worker() -> None:
        try:
            result = agent.run(run_request.goal)
            duration_ms = int((perf_counter() - started_at) * 1000)
            # 保存任务结果到数据库
            try:
                store.save_task(
                    task_id=task_id,
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

    event_queue.put({"type": "run_boot", "goal": run_request.goal, "run_id": run_id, "task_id": task_id, "session_id": session_id})
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
