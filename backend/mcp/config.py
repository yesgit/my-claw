from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class MCPServerConfig:
    name: str
    command: list[str]
    cwd: str | None = None
    env: dict[str, str] | None = None


def load_mcp_server_configs(config_path: str | Path) -> list[MCPServerConfig]:
    path = Path(config_path)
    try:
        if not path.exists():
            return []
    except PermissionError:
        return []

    payload = json.loads(path.read_text(encoding="utf-8"))
    servers = payload.get("servers", [])
    if not isinstance(servers, list):
        raise ValueError("MCP config 的 servers 必须是列表")

    result: list[MCPServerConfig] = []
    for item in servers:
        if not isinstance(item, dict):
            raise ValueError("MCP config 中的 server 必须是对象")
        name = item.get("name")
        command = item.get("command")
        if not name or not isinstance(command, list) or not all(isinstance(arg, str) for arg in command):
            raise ValueError("MCP server 配置需要 name 和 command(list[str])")
        cwd = item.get("cwd")
        env = item.get("env")
        if env is not None and not isinstance(env, dict):
            raise ValueError("MCP server 配置的 env 必须是对象")
        result.append(
            MCPServerConfig(
                name=name,
                command=command,
                cwd=cwd,
                env=env,
            )
        )
    return result
