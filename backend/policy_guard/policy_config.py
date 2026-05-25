"""全局策略配置：默认策略模式 + 安全护栏开关。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from typing import Any

# 默认配置文件路径
_DEFAULT_CONFIG_PATH = Path.home() / ".myclaw" / "policy_config.json"

# 合法的策略模式
VALID_MODES = {"strict", "standard", "permissive"}


@dataclass(slots=True)
class SafetyRails:
    """安全护栏开关。"""

    # 高风险操作始终需审批（如 delete_file, shell.execute）
    high_risk_always_approve: bool = True
    # 修改/删除文件必须逐个审批
    file_modify_one_by_one: bool = True
    # Shell 命令必须逐个审批
    shell_one_by_one: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "high_risk_always_approve": self.high_risk_always_approve,
            "file_modify_one_by_one": self.file_modify_one_by_one,
            "shell_one_by_one": self.shell_one_by_one,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SafetyRails:
        return cls(
            high_risk_always_approve=data.get("high_risk_always_approve", True),
            file_modify_one_by_one=data.get("file_modify_one_by_one", True),
            shell_one_by_one=data.get("shell_one_by_one", False),
        )


@dataclass(slots=True)
class PolicyConfig:
    """全局策略配置。"""

    # 策略模式: strict / standard / permissive
    mode: str = "standard"
    # 安全护栏
    safety_rails: SafetyRails = field(default_factory=SafetyRails)

    def __post_init__(self) -> None:
        if self.mode not in VALID_MODES:
            self.mode = "standard"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "safety_rails": self.safety_rails.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyConfig:
        rails_data = data.get("safety_rails", {})
        return cls(
            mode=data.get("mode", "standard"),
            safety_rails=SafetyRails.from_dict(rails_data),
        )


def load_policy_config(path: str | Path | None = None) -> PolicyConfig:
    """从磁盘加载策略配置。文件不存在时返回默认配置。"""
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return PolicyConfig()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        return PolicyConfig.from_dict(raw)
    except Exception:
        return PolicyConfig()


def save_policy_config(config: PolicyConfig, path: str | Path | None = None) -> None:
    """将策略配置写入磁盘。"""
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


