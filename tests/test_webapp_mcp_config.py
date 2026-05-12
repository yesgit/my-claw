from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import webapp
from backend.memory.conversation_store import ConversationStore


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

    def test_create_session_uses_llm_for_name_when_blank(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            conversation_db = Path(tmp_dir) / "conversations.db"

            def conversation_store_factory() -> ConversationStore:
                return ConversationStore(db_path=conversation_db)

            class FakeOpenAIClient:
                last_messages = None

                def __init__(self, config) -> None:  # noqa: ANN001
                    self.config = config

                def chat(self, messages, temperature: float = 0.0) -> str:  # noqa: ANN001
                    FakeOpenAIClient.last_messages = messages
                    return json.dumps({"name": "后端结构梳理"}, ensure_ascii=False)

            model_config = webapp.ModelConfigPayload(
                defaultProviderId="openai-local",
                defaultModelId="gpt-4.1-mini",
                providers=[
                    webapp.ModelProvider(
                        id="openai-local",
                        name="Local Default",
                        baseUrl="http://fake-llm/v1",
                        apiKey="fake-key",
                        timeout=30.0,
                        jsonMode=True,
                        models=[
                            webapp.ProviderModel(
                                id="gpt-4.1-mini",
                                name="GPT 4.1 Mini",
                                model="gpt-4.1-mini",
                            )
                        ],
                    )
                ],
            )

            with patch("backend.webapp.ConversationStore", new=conversation_store_factory), patch(
                "backend.webapp._load_model_config",
                return_value=model_config,
            ), patch("backend.webapp.OpenAICompatibleChatClient", new=FakeOpenAIClient):
                result = webapp.create_session(
                    webapp.CreateSessionRequest(
                        name="",
                        seedGoal="请总结 backend 目录结构",
                        config=webapp.SessionConfigPayload(
                            providerId="openai-local",
                            modelId="gpt-4.1-mini",
                        ),
                    )
                )

                self.assertTrue(result["ok"])
                self.assertEqual(result["session"]["name"], "后端结构梳理")
                self.assertIsNotNone(FakeOpenAIClient.last_messages)
                self.assertIn("请总结 backend 目录结构", FakeOpenAIClient.last_messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
