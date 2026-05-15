from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.main import build_mcp_manager
from backend.mcp import load_mcp_server_configs


class TestMCPDemoServerIntegration(unittest.TestCase):
    def test_load_config_and_list_tools(self) -> None:
        config_path = Path(__file__).resolve().parent.parent / "examples" / "mcp_servers.example.json"
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
