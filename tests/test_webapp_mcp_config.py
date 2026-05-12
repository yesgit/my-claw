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
                self.assertEqual(payload["servers"], [])

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

    def test_validate_uses_inline_servers_when_present(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fake_config_path = Path(tmp_dir) / "mcp_config.json"
            with patch("backend.webapp.MCP_CONFIG_PATH", fake_config_path):
                client = TestClient(webapp.app)

                put_resp = client.put(
                    "/api/mcp-config",
                    json={
                        "defaultConfigPath": "",
                        "servers": [
                            {
                                "name": "demo-inline",
                                "command": ["python", "-m", "backend.mcp.demo_server"],
                                "cwd": "/root/projects/my-claw",
                                "env": {"A": "1"},
                            }
                        ],
                    },
                )
                self.assertEqual(put_resp.status_code, 200)

                resp = client.post("/api/mcp-config/validate", json={"configPath": None})
                self.assertEqual(resp.status_code, 200)
                payload = resp.json()
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["source"], "inline")
                self.assertEqual(payload["count"], 1)
                self.assertEqual(payload["servers"][0]["name"], "demo-inline")

    def test_test_server_endpoint_success(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fake_config_path = Path(tmp_dir) / "mcp_config.json"
            with patch("backend.webapp.MCP_CONFIG_PATH", fake_config_path):
                client = TestClient(webapp.app)
                with patch(
                    "backend.webapp._test_single_mcp_server",
                    return_value={
                        "ok": True,
                        "server": "demo",
                        "latencyMs": 12,
                        "protocolVersion": "2026-01-01",
                        "toolCount": 1,
                        "toolNames": ["read_file"],
                    },
                ):
                    resp = client.post(
                        "/api/mcp-config/test-server",
                        json={
                            "server": {
                                "name": "demo",
                                "command": ["python", "-m", "backend.mcp.demo_server"],
                                "cwd": "/root/projects/my-claw",
                                "env": {},
                            }
                        },
                    )

                self.assertEqual(resp.status_code, 200)
                payload = resp.json()
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["server"], "demo")
                self.assertEqual(payload["toolCount"], 1)

    def test_test_server_endpoint_bad_payload(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fake_config_path = Path(tmp_dir) / "mcp_config.json"
            with patch("backend.webapp.MCP_CONFIG_PATH", fake_config_path):
                client = TestClient(webapp.app)
                resp = client.post(
                    "/api/mcp-config/test-server",
                    json={
                        "server": {
                            "name": "demo",
                            "command": [],
                        }
                    },
                )

                self.assertEqual(resp.status_code, 400)
                payload = resp.json()
                self.assertIn("MCP server 参数非法", payload["detail"])


if __name__ == "__main__":
    unittest.main()
