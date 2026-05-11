from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from backend.models import OperationRequest


class ChatPlannerClient(Protocol):
    def chat(self, messages: list[dict[str, str]], temperature: float = 0.0) -> str:
        ...


@dataclass(slots=True)
class LLMPlanner:
    client: ChatPlannerClient
    model_name: str

    def plan(self, goal: str) -> OperationRequest:
        goal = goal.strip()
        if not goal:
            raise ValueError("目标不能为空")

        content = self.client.chat(
            [
                {
                    "role": "system",
                    "content": self._system_prompt(),
                },
                {
                    "role": "user",
                    "content": goal,
                },
            ],
            temperature=0.0,
        )
        return self._parse_operation(content)

    def _system_prompt(self) -> str:
        return (
            "你是一个任务规划器，只能输出一个 JSON 对象，不能输出解释、代码块或多余文本。"
            "JSON 必须满足以下严格约束：\n"
            "1. 只允许这些键：tool, action, resource, params, risk。\n"
            "2. tool 只能是 filesystem 或 mcp。\n"
            "3. action 必须是字符串，且是具体工具动作名。\n"
            "4. resource 必须是字符串。filesystem 通常使用本地路径；mcp 必须使用 mcp://server/tool。\n"
            "5. params 必须是对象。\n"
            "6. risk 只能是 low, medium, high。\n"
            "7. 不允许额外字段。\n"
            "输出示例：{\"tool\":\"filesystem\",\"action\":\"read_file\",\"resource\":\"/tmp/a.txt\",\"params\":{},\"risk\":\"medium\"}"
        )

    def _parse_operation(self, content: str) -> OperationRequest:
        candidate = self._extract_json(content)
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM 输出不是有效 JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("LLM 输出必须是 JSON 对象")

        allowed_keys = {"tool", "action", "resource", "params", "risk"}
        payload_keys = set(payload.keys())
        if not payload_keys.issubset(allowed_keys):
            extra_keys = sorted(payload_keys - allowed_keys)
            raise ValueError(f"LLM 输出包含不允许的字段：{', '.join(extra_keys)}")

        required_keys = {"tool", "action", "resource"}
        if not required_keys.issubset(payload_keys):
            raise ValueError("LLM 输出缺少必要字段：tool/action/resource")

        tool = payload["tool"]
        action = payload["action"]
        resource = payload["resource"]
        params = payload.get("params", {})
        risk = payload.get("risk", "medium")

        if not isinstance(tool, str) or tool not in {"filesystem", "mcp"}:
            raise ValueError("LLM 输出 tool 必须是 filesystem 或 mcp")
        if not isinstance(action, str) or not action.strip():
            raise ValueError("LLM 输出 action 必须是非空字符串")
        if not isinstance(resource, str) or not resource.strip():
            raise ValueError("LLM 输出 resource 必须是非空字符串")
        if not isinstance(params, dict):
            raise ValueError("LLM 输出 params 必须是对象")
        if not isinstance(risk, str) or risk not in {"low", "medium", "high"}:
            raise ValueError("LLM 输出 risk 必须是 low, medium, high 之一")

        if tool == "mcp" and not resource.startswith("mcp://"):
            raise ValueError("当 tool 为 mcp 时，resource 必须是 mcp://server/tool 格式")

        return OperationRequest(
            tool=tool,
            action=action,
            resource=resource,
            params=params,
            risk=risk,
        )

    def _extract_json(self, content: str) -> str:
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if fenced:
            return fenced.group(1)

        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("LLM 输出中未找到 JSON 对象")
        return content[start : end + 1]