from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import webapp


class TestWebappMCPConfig(unittest.TestCase):
    def test_get_default_config_when_file_missing(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fake_config_path = Path(tmp_dir) / "mcp_config.json"
            with patch("backend.webapp.MCP_CONFIG_PATH", fake_config_path):
                client = TestClient(webapp.app)
                resp = client.get("/api/mcp-config")

                self.assertEqual(resp.status_code, 200)
                payload = resp.json()
                self.assertEqual(payload["defaultConfigPath"], "")

    def test_put_and_get_config(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fake_config_path = Path(tmp_dir) / "mcp_config.json"
            target_mcp = Path(tmp_dir) / "servers.json"
            target_mcp.write_text(json.dumps({"servers": []}, ensure_ascii=False), encoding="utf-8")

            with patch("backend.webapp.MCP_CONFIG_PATH", fake_config_path):
                client = TestClient(webapp.app)

                put_resp = client.put(
                    "/api/mcp-config",
                    json={"defaultConfigPath": str(target_mcp)},
                )
                self.assertEqual(put_resp.status_code, 200)

                get_resp = client.get("/api/mcp-config")
                self.assertEqual(get_resp.status_code, 200)
                payload = get_resp.json()
                self.assertEqual(payload["defaultConfigPath"], str(target_mcp))

    def test_validate_config_returns_servers(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fake_config_path = Path(tmp_dir) / "mcp_config.json"
            mcp_path = Path(tmp_dir) / "servers.json"
            mcp_path.write_text(
                json.dumps(
                    {
                        "servers": [
                            {
                                "name": "demo",
                                "command": ["python", "-m", "backend.mcp.demo_server"],
                                "cwd": "/root/projects/my-claw",
                                "env": {"A": "1"},
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch("backend.webapp.MCP_CONFIG_PATH", fake_config_path):
                client = TestClient(webapp.app)
                resp = client.post(
                    "/api/mcp-config/validate",
                    json={"configPath": str(mcp_path)},
                )

                self.assertEqual(resp.status_code, 200)
                payload = resp.json()
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["count"], 1)
                self.assertEqual(payload["servers"][0]["name"], "demo")
                self.assertEqual(payload["servers"][0]["envCount"], 1)


if __name__ == "__main__":
    unittest.main()
