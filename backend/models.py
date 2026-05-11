from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class OperationRequest:
    tool: str
    action: str
    resource: str
    params: dict[str, Any] = field(default_factory=dict)
    risk: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "action": self.action,
            "resource": self.resource,
            "params": self.params,
            "risk": self.risk,
        }
