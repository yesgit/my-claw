from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class PolicyRule:
    id: str
    tool: str
    action: str
    resource: str
    effect: str
    created_at: str
    expires_at: str | None = None
    max_risk: str | None = None  # 规则生效的风险上限，如 "medium" 表示只匹配 risk≤medium 的操作

    def is_expired(self, now: datetime) -> bool:
        if not self.expires_at:
            return False

        try:
            expires_at = datetime.fromisoformat(self.expires_at)
        except ValueError:
            return False

        return now >= expires_at
