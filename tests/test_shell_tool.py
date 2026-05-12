from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.models import OperationRequest
from backend.tools.shell.tool import ShellTool


def _op(command: str, cwd: str | None = None, timeout: float | None = None) -> OperationRequest:
    params: dict = {"command": command}
    if cwd is not None:
        params["cwd"] = cwd
    if timeout is not None:
        params["timeout"] = timeout
    return OperationRequest(
        tool="shell",
        action="run_command",
        resource="",
        params=params,
        risk="high",
    )


class TestShellToolBasic(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = ShellTool()

    # ── 正常执行 ──────────────────────────────────────
    def test_echo_returns_stdout(self) -> None:
        result = self.tool.execute(_op("echo hello"))
        self.assertTrue(result["ok"])
        self.assertIn("hello", result["stdout"])
        self.assertEqual(result["returncode"], 0)

    def test_nonzero_exit_sets_ok_false(self) -> None:
        result = self.tool.execute(_op("exit 1"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["returncode"], 1)

    def test_stderr_captured(self) -> None:
        result = self.tool.execute(_op("echo err >&2"))
        self.assertIn("err", result["stderr"])

    def test_cwd_is_applied(self) -> None:
        with TemporaryDirectory() as tmp:
            result = self.tool.execute(_op("pwd", cwd=tmp))
            self.assertTrue(result["ok"])
            # resolved 路径应与 tmp 的真实路径一致
            self.assertEqual(
                Path(result["stdout"].strip()).resolve(),
                Path(tmp).resolve(),
            )

    def test_invalid_cwd_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.tool.execute(_op("echo x", cwd="/nonexistent_dir_abc"))

    def test_timeout_param_too_large_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.tool.execute(_op("echo x", timeout=9999))

    def test_timeout_param_zero_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.tool.execute(_op("echo x", timeout=0))

    # ── 参数校验 ────────────────────────────────────────
    def test_empty_command_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.tool.execute(_op(""))

    def test_unsupported_action_raises(self) -> None:
        op = OperationRequest(tool="shell", action="unknown_action", resource="", params={}, risk="high")
        with self.assertRaises(ValueError):
            self.tool.execute(op)

    # ── 安全黑名单 ────────────────────────────────────────
    def test_rm_rf_root_blocked(self) -> None:
        with self.assertRaises(ValueError):
            self.tool.execute(_op("rm -rf /"))

    def test_rm_rf_glob_blocked(self) -> None:
        with self.assertRaises(ValueError):
            self.tool.execute(_op("rm -rf /*"))

    def test_sudo_blocked(self) -> None:
        with self.assertRaises(ValueError):
            self.tool.execute(_op("sudo ls"))

    def test_interactive_vim_blocked(self) -> None:
        with self.assertRaises(ValueError):
            self.tool.execute(_op("vim /tmp/test.txt"))

    def test_interactive_nano_blocked(self) -> None:
        with self.assertRaises(ValueError):
            self.tool.execute(_op("nano /tmp/test.txt"))

    # ── describe() ───────────────────────────────────────
    def test_describe_returns_expected_keys(self) -> None:
        desc = self.tool.describe()
        self.assertEqual(desc["tool"], "shell")
        self.assertEqual(desc["type"], "local")
        self.assertTrue(any(action["name"] == "run_command" for action in desc["actions"]))
        self.assertIn("input_schema", desc)
        self.assertEqual(desc["tool_name"], "shell")
        self.assertIn("run_command", desc["supported_actions"])
        self.assertEqual(desc["supported_actions"]["run_command"], "high")

    # ── 输出截断 ──────────────────────────────────────────
    def test_large_output_truncated(self) -> None:
        # 生成超过 10000 字符的输出
        result = self.tool.execute(_op("python3 -c \"print('x' * 20000)\""))
        self.assertTrue(result["ok"])
        self.assertLessEqual(len(result["stdout"]), 11000)
        self.assertIn("截断", result["stdout"])


if __name__ == "__main__":
    unittest.main()
