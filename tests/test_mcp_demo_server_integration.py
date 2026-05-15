from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.main import build_mcp_manager
from backend.mcp import load_mcp_server_configs


class TestMCPDemoServerIntegration(unittest.TestCase):
    def test_load_config_and_list_tools(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        # 构建可在任何环境运行的临时配置（使用当前 Python 解释器 + 动态 cwd）
        with TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "mcp.json"
            config_path.write_text(
                json.dumps(
                    {
                        "servers": [
                            {
                                "name": "demo-filesystem",
                                "command": [sys.executable, "-m", "backend.mcp.demo_server"],
                                "cwd": str(project_root),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            configs = load_mcp_server_configs(config_path)
            self.assertEqual(len(configs), 1)
            self.assertEqual(configs[0].name, "demo-filesystem")

            manager = build_mcp_manager(str(config_path))
            try:
                self.assertIn("demo-filesystem", manager.list_servers())
                tools = manager.list_tools("demo-filesystem")
                tool_names = [tool["name"] for tool in tools]
                self.assertIn("read_file", tool_names)
                self.assertIn("list_dir", tool_names)
            finally:
                manager.close_all()

    def test_load_invalid_config_raises(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "bad.json"
            path.write_text(json.dumps({"servers": [{"name": "x", "command": "not-a-list"}]}), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_mcp_server_configs(path)


if __name__ == "__main__":
    unittest.main()