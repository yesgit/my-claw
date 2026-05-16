from __future__ import annotations

import subprocess
import shlex
from pathlib import Path

from backend.models import OperationRequest


class ShellTool:
    """Shell 命令执行工具。默认 risk=high，每次执行都需要审批。"""

    tool_name = "shell"
    description = "Shell 命令执行工具，支持在系统终端中运行命令（默认 risk=high，每次执行都需要审批）"
    supported_actions = {
        "run_command": "high",
    }

    # 禁止执行的命令前缀（黑名单）
    FORBIDDEN_PREFIXES = [
        "rm -rf /",
        "rm -rf /*",
        "rm -rf ~",
        "mkfs.",
        "dd if=",
        ":(){ :|:& };:",
        "> /dev/sda",
        "| sh",
        "sudo ",
        "su ",
        "chmod 777 /",
        "chown ",
    ]

    def describe(self) -> dict:
        """返回工具的标准自描述信息。"""
        actions = [
            {"name": action, "default_risk": risk}
            for action, risk in self.supported_actions.items()
        ]
        return {
            # 新版统一字段
            "tool": self.tool_name,
            "type": "local",
            "actions": actions,
            "input_schema": {},
            # 兼容旧字段
            "tool_name": self.tool_name,
            "description": self.description,
            "supported_actions": dict(self.supported_actions),
        }

    def execute(self, operation: OperationRequest) -> dict:
        if operation.action == "run_command":
            return self._run_command(operation)

        raise ValueError(f"不支持的 action: {operation.action}")

    def _run_command(self, operation: OperationRequest) -> dict:
        command = operation.params.get("command", "")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("run_command 需要 params.command 为非空字符串")

        # 安全检查
        self._validate_command(command)

        cwd_value = operation.params.get("cwd")
        cwd = Path(cwd_value).resolve() if cwd_value else None
        if cwd and not cwd.is_dir():
            raise ValueError(f"cwd 目录不存在: {cwd}")

        timeout = float(operation.params.get("timeout", 30))
        if timeout <= 0 or timeout > 300:
            raise ValueError("timeout 必须在 1-300 秒之间")

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(cwd) if cwd else None,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "tool": self.tool_name,
                "action": operation.action,
                "error": f"命令执行超时（{timeout}秒）",
                "command": command,
            }
        except Exception as exc:
            return {
                "ok": False,
                "tool": self.tool_name,
                "action": operation.action,
                "error": str(exc),
                "command": command,
            }

        output = {
            "ok": result.returncode == 0,
            "tool": self.tool_name,
            "action": operation.action,
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

        # 限制输出大小，防止 LLM 上下文爆炸
        max_output = 4000
        for key in ("stdout", "stderr"):
            if len(output.get(key, "")) > max_output:
                output[key] = output[key][:max_output] + f"\n...（截断，共 {len(output[key])} 字符）"

        return output

    def _validate_command(self, command: str) -> None:
        """执行安全检查"""
        stripped = command.strip().lower()

        # 检查黑名单前缀
        for prefix in self.FORBIDDEN_PREFIXES:
            if stripped.startswith(prefix.lower()):
                raise ValueError(f"禁止执行危险命令（匹配黑名单前缀: {prefix}）")

        # 检查是否包含交互式命令
        interactive_commands = ["vim", "nano", "less", "more", "top", "htop", "vi"]
        first_word = shlex.split(command)[0] if shlex.split(command) else ""
        if first_word in interactive_commands:
            raise ValueError(f"禁止执行交互式命令: {first_word}")
