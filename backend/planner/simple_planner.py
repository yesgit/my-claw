from __future__ import annotations

import json
from pathlib import Path

from backend.models import OperationRequest


class SimplePlanner:
    """A minimal planner for MVP step 1.

    It accepts either:
    1) JSON operation text that matches the OperationRequest schema.
    2) Free-form goal text, which will be converted into a default write_file action.
    """

    def plan(self, goal: str) -> OperationRequest:
        goal = goal.strip()
        if not goal:
            raise ValueError("目标不能为空")

        maybe_json = self._try_parse_json(goal)
        if maybe_json is not None:
            return maybe_json

        default_path = Path.cwd() / "output" / "agent-output.txt"
        return OperationRequest(
            tool="filesystem",
            action="write_file",
            resource=str(default_path),
            params={"mode": "overwrite", "content": goal},
            risk="medium",
        )

    def _try_parse_json(self, text: str) -> OperationRequest | None:
        if not text.startswith("{"):
            return None

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None

        required_keys = {"tool", "action", "resource"}
        if not required_keys.issubset(payload.keys()):
            raise ValueError("JSON 操作缺少必要字段：tool/action/resource")

        return OperationRequest(
            tool=payload["tool"],
            action=payload["action"],
            resource=payload["resource"],
            params=payload.get("params", {}),
            risk=payload.get("risk", "medium"),
        )
