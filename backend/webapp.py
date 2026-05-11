from __future__ import annotations

from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.agent import ReactAgent
from backend.llm import OpenAICompatibleChatClient, OpenAICompatibleConfig
from backend.mcp import MCPClientManager, MCPServerClient, StdIOTransport, load_mcp_server_configs
from backend.memory.rule_store import RuleStore
from backend.policy_guard.guard import PolicyGuard
from backend.tool_router.router import ToolRouter

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "ui" / "web"

app = FastAPI(title="MyClaw Web UI", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ReactRunRequest(BaseModel):
    goal: str = Field(min_length=1)
    llmBaseUrl: str = Field(min_length=1)
    llmApiKey: str = Field(min_length=1)
    llmModel: str = Field(min_length=1)
    llmTimeout: float = Field(default=60.0, ge=1.0, le=300.0)
    maxSteps: int = Field(default=8, ge=1, le=30)
    approvalDecision: str = Field(default="1")
    mcpConfig: str | None = None
    jsonMode: bool = True


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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/run-react")
def run_react(payload: ReactRunRequest) -> dict:
    if payload.approvalDecision not in {"1", "2", "3", "4", "y", "n"}:
        raise HTTPException(status_code=400, detail="approvalDecision 必须是 1/2/3/4/y/n")

    rule_store = RuleStore()
    guard = PolicyGuard(input_func=lambda _: payload.approvalDecision, rule_store=rule_store)
    mcp_manager = _build_mcp_manager(payload.mcpConfig)
    router = ToolRouter(mcp_manager=mcp_manager)
    client = OpenAICompatibleChatClient(
        OpenAICompatibleConfig(
            base_url=payload.llmBaseUrl,
            api_key=payload.llmApiKey,
            model=payload.llmModel,
            timeout=payload.llmTimeout,
            json_mode=payload.jsonMode,
        )
    )
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
