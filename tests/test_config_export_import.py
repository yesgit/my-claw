"""配置导出/导入 API 的单元测试"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import webapp


class TestConfigExport(unittest.TestCase):
    def test_export_both(self) -> None:
        """导出模型和 MCP 两个模块"""
        with TemporaryDirectory() as tmp_dir:
            model_path = Path(tmp_dir) / "model_profiles.json"
            mcp_path = Path(tmp_dir) / "mcp_config.json"

            with (
                patch("backend.webapp.MODEL_CONFIG_PATH", model_path),
                patch("backend.webapp.MCP_CONFIG_PATH", mcp_path),
            ):
                client = TestClient(webapp.app)

                # 保存模型配置
                sample_model = {
                    "defaultProviderId": "test-provider",
                    "defaultModelId": "test-model",
                    "providers": [
                        {
                            "id": "test-provider",
                            "name": "Test Provider",
                            "baseUrl": "http://localhost:11434/v1",
                            "apiKey": "sk-test-12345678",
                            "apiKeyEnvVar": "",
                            "timeout": 60.0,
                            "jsonMode": True,
                            "models": [
                                {"id": "test-model", "name": "Test Model", "model": "test-model", "flash": False}
                            ],
                        }
                    ],
                }
                client.put("/api/model-config", json=sample_model)

                # 保存 MCP 配置
                sample_mcp = {
                    "defaultConfigPath": "",
                    "servers": [
                        {"name": "test-server", "command": ["python", "-m", "some_server"], "cwd": None, "env": {}}
                    ],
                }
                client.put("/api/mcp-config", json=sample_mcp)

                # 导出
                resp = client.post("/api/config/export", json={"exportModels": True, "exportMcp": True})
                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertTrue(body["ok"])
                data = body["data"]
                self.assertEqual(data["version"], "1.0")
                self.assertIn("exportedAt", data)
                self.assertIn("models", data)
                self.assertIn("mcp", data)
                self.assertEqual(data["models"]["defaultProviderId"], "test-provider")
                self.assertEqual(len(data["mcp"]["servers"]), 1)

    def test_export_models_only(self) -> None:
        """仅导出模型配置"""
        with TemporaryDirectory() as tmp_dir:
            model_path = Path(tmp_dir) / "model_profiles.json"
            mcp_path = Path(tmp_dir) / "mcp_config.json"

            with (
                patch("backend.webapp.MODEL_CONFIG_PATH", model_path),
                patch("backend.webapp.MCP_CONFIG_PATH", mcp_path),
            ):
                client = TestClient(webapp.app)
                sample_model = {
                    "defaultProviderId": "tp",
                    "defaultModelId": "tm",
                    "providers": [
                        {
                            "id": "tp",
                            "name": "TP",
                            "baseUrl": "http://localhost:11434/v1",
                            "apiKey": "sk-test",
                            "apiKeyEnvVar": "",
                            "timeout": 60.0,
                            "jsonMode": True,
                            "models": [{"id": "tm", "name": "TM", "model": "tm"}],
                        }
                    ],
                }
                client.put("/api/model-config", json=sample_model)

                resp = client.post("/api/config/export", json={"exportModels": True, "exportMcp": False})
                self.assertEqual(resp.status_code, 200)
                data = resp.json()["data"]
                self.assertIn("models", data)
                self.assertNotIn("mcp", data)

    def test_export_mcp_only(self) -> None:
        """仅导出 MCP 配置"""
        with TemporaryDirectory() as tmp_dir:
            model_path = Path(tmp_dir) / "model_profiles.json"
            mcp_path = Path(tmp_dir) / "mcp_config.json"

            with (
                patch("backend.webapp.MODEL_CONFIG_PATH", model_path),
                patch("backend.webapp.MCP_CONFIG_PATH", mcp_path),
            ):
                client = TestClient(webapp.app)
                client.put("/api/mcp-config", json={"defaultConfigPath": "", "servers": []})

                resp = client.post("/api/config/export", json={"exportModels": False, "exportMcp": True})
                self.assertEqual(resp.status_code, 200)
                data = resp.json()["data"]
                self.assertNotIn("models", data)
                self.assertIn("mcp", data)

    def test_export_includes_api_key(self) -> None:
        """导出时应该包含完整 API Key（不是掩码）"""
        with TemporaryDirectory() as tmp_dir:
            model_path = Path(tmp_dir) / "model_profiles.json"
            mcp_path = Path(tmp_dir) / "mcp_config.json"

            with (
                patch("backend.webapp.MODEL_CONFIG_PATH", model_path),
                patch("backend.webapp.MCP_CONFIG_PATH", mcp_path),
            ):
                client = TestClient(webapp.app)
                sample_model = {
                    "defaultProviderId": "tp",
                    "defaultModelId": "tm",
                    "providers": [
                        {
                            "id": "tp",
                            "name": "TP",
                            "baseUrl": "http://localhost:11434/v1",
                            "apiKey": "sk-test-12345678",
                            "apiKeyEnvVar": "",
                            "timeout": 60.0,
                            "jsonMode": True,
                            "models": [{"id": "tm", "name": "TM", "model": "tm"}],
                        }
                    ],
                }
                client.put("/api/model-config", json=sample_model)

                resp = client.post("/api/config/export", json={"exportModels": True, "exportMcp": False})
                exported_key = resp.json()["data"]["models"]["providers"][0]["apiKey"]
                self.assertEqual(exported_key, "sk-test-12345678")


class TestConfigImport(unittest.TestCase):
    def _sample_model_config(self) -> dict:
        return {
            "defaultProviderId": "test-provider",
            "defaultModelId": "test-model",
            "providers": [
                {
                    "id": "test-provider",
                    "name": "Test Provider",
                    "baseUrl": "http://localhost:11434/v1",
                    "apiKey": "sk-test-12345678",
                    "apiKeyEnvVar": "",
                    "timeout": 60.0,
                    "jsonMode": True,
                    "models": [
                        {"id": "test-model", "name": "Test Model", "model": "test-model", "flash": False}
                    ],
                }
            ],
        }

    def _sample_mcp_config(self) -> dict:
        return {
            "defaultConfigPath": "",
            "servers": [
                {
                    "name": "test-server",
                    "command": ["python", "-m", "some_server"],
                    "cwd": None,
                    "env": {},
                }
            ],
        }

    def test_import_both(self) -> None:
        """导入模型和 MCP 两个模块"""
        with TemporaryDirectory() as tmp_dir:
            model_path = Path(tmp_dir) / "model_profiles.json"
            mcp_path = Path(tmp_dir) / "mcp_config.json"

            with (
                patch("backend.webapp.MODEL_CONFIG_PATH", model_path),
                patch("backend.webapp.MCP_CONFIG_PATH", mcp_path),
            ):
                client = TestClient(webapp.app)

                export_payload = {
                    "version": "1.0",
                    "exportedAt": "2026-01-01T00:00:00",
                    "models": self._sample_model_config(),
                    "mcp": self._sample_mcp_config(),
                }

                resp = client.post(
                    "/api/config/import",
                    json={"payload": export_payload, "importModels": True, "importMcp": True},
                )
                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertTrue(body["ok"])
                self.assertIn("models", body["imported"])
                self.assertIn("mcp", body["imported"])

                # 验证模型配置已写入
                get_resp = client.get("/api/model-config")
                self.assertEqual(get_resp.json()["defaultProviderId"], "test-provider")

                # 验证 MCP 配置已写入
                mcp_resp = client.get("/api/mcp-config")
                self.assertEqual(len(mcp_resp.json()["servers"]), 1)

    def test_import_models_only(self) -> None:
        """仅导入模型配置"""
        with TemporaryDirectory() as tmp_dir:
            model_path = Path(tmp_dir) / "model_profiles.json"
            mcp_path = Path(tmp_dir) / "mcp_config.json"

            with (
                patch("backend.webapp.MODEL_CONFIG_PATH", model_path),
                patch("backend.webapp.MCP_CONFIG_PATH", mcp_path),
            ):
                client = TestClient(webapp.app)

                export_payload = {
                    "version": "1.0",
                    "exportedAt": "2026-01-01T00:00:00",
                    "models": self._sample_model_config(),
                    "mcp": self._sample_mcp_config(),
                }

                resp = client.post(
                    "/api/config/import",
                    json={"payload": export_payload, "importModels": True, "importMcp": False},
                )
                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertIn("models", body["imported"])
                self.assertNotIn("mcp", body["imported"])

    def test_import_skips_missing_module(self) -> None:
        """导出数据中不包含某模块时，该模块应被跳过"""
        with TemporaryDirectory() as tmp_dir:
            model_path = Path(tmp_dir) / "model_profiles.json"
            mcp_path = Path(tmp_dir) / "mcp_config.json"

            with (
                patch("backend.webapp.MODEL_CONFIG_PATH", model_path),
                patch("backend.webapp.MCP_CONFIG_PATH", mcp_path),
            ):
                client = TestClient(webapp.app)

                export_payload = {
                    "version": "1.0",
                    "exportedAt": "2026-01-01T00:00:00",
                }

                resp = client.post(
                    "/api/config/import",
                    json={"payload": export_payload, "importModels": True, "importMcp": True},
                )
                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertEqual(body["imported"], [])
                self.assertTrue(body["models"]["skipped"])
                self.assertTrue(body["mcp"]["skipped"])

    def test_import_rejects_bad_version(self) -> None:
        """版本号不匹配时应拒绝导入"""
        with TemporaryDirectory() as tmp_dir:
            model_path = Path(tmp_dir) / "model_profiles.json"
            mcp_path = Path(tmp_dir) / "mcp_config.json"

            with (
                patch("backend.webapp.MODEL_CONFIG_PATH", model_path),
                patch("backend.webapp.MCP_CONFIG_PATH", mcp_path),
            ):
                client = TestClient(webapp.app)

                export_payload = {"version": "2.0", "exportedAt": "2026-01-01T00:00:00"}

                resp = client.post(
                    "/api/config/import",
                    json={"payload": export_payload, "importModels": True, "importMcp": True},
                )
                self.assertEqual(resp.status_code, 400)
                self.assertIn("版本", resp.json()["detail"])

    def test_import_preserves_existing_api_key(self) -> None:
        """导入时如果导入数据 apiKey 为空，应保留本地已有的 apiKey"""
        with TemporaryDirectory() as tmp_dir:
            model_path = Path(tmp_dir) / "model_profiles.json"
            mcp_path = Path(tmp_dir) / "mcp_config.json"

            with (
                patch("backend.webapp.MODEL_CONFIG_PATH", model_path),
                patch("backend.webapp.MCP_CONFIG_PATH", mcp_path),
            ):
                client = TestClient(webapp.app)

                # 先保存有 apiKey 的配置
                client.put("/api/model-config", json=self._sample_model_config())

                # 导入 apiKey 为空的配置
                import_model = json.loads(json.dumps(self._sample_model_config()))
                import_model["providers"][0]["apiKey"] = ""

                export_payload = {
                    "version": "1.0",
                    "exportedAt": "2026-01-01T00:00:00",
                    "models": import_model,
                }

                resp = client.post(
                    "/api/config/import",
                    json={"payload": export_payload, "importModels": True, "importMcp": False},
                )
                self.assertEqual(resp.status_code, 200)

                # 验证 apiKey 被保留
                reveal_resp = client.get("/api/model-config/test-provider/reveal-key")
                self.assertEqual(reveal_resp.json()["apiKey"], "sk-test-12345678")

    def test_import_rejects_invalid_model_config(self) -> None:
        """导入无效的模型配置应报错"""
        with TemporaryDirectory() as tmp_dir:
            model_path = Path(tmp_dir) / "model_profiles.json"
            mcp_path = Path(tmp_dir) / "mcp_config.json"

            with (
                patch("backend.webapp.MODEL_CONFIG_PATH", model_path),
                patch("backend.webapp.MCP_CONFIG_PATH", mcp_path),
            ):
                client = TestClient(webapp.app)

                export_payload = {
                    "version": "1.0",
                    "exportedAt": "2026-01-01T00:00:00",
                    "models": {
                        "defaultProviderId": "x",
                        "defaultModelId": "y",
                        "providers": [],
                    },
                }

                resp = client.post(
                    "/api/config/import",
                    json={"payload": export_payload, "importModels": True, "importMcp": False},
                )
                self.assertEqual(resp.status_code, 400)
                self.assertIn("模型配置导入失败", resp.json()["detail"])


class TestConfigExportImportRoundtrip(unittest.TestCase):
    def test_roundtrip(self) -> None:
        """完整导出 → 导入的往返测试"""
        with TemporaryDirectory() as tmp_dir:
            model_path = Path(tmp_dir) / "model_profiles.json"
            mcp_path = Path(tmp_dir) / "mcp_config.json"

            with (
                patch("backend.webapp.MODEL_CONFIG_PATH", model_path),
                patch("backend.webapp.MCP_CONFIG_PATH", mcp_path),
            ):
                client = TestClient(webapp.app)

                sample_model = {
                    "defaultProviderId": "test-provider",
                    "defaultModelId": "test-model",
                    "providers": [
                        {
                            "id": "test-provider",
                            "name": "Test Provider",
                            "baseUrl": "http://localhost:11434/v1",
                            "apiKey": "sk-test-12345678",
                            "apiKeyEnvVar": "",
                            "timeout": 60.0,
                            "jsonMode": True,
                            "models": [
                                {"id": "test-model", "name": "Test Model", "model": "test-model", "flash": False}
                            ],
                        }
                    ],
                }
                sample_mcp = {
                    "defaultConfigPath": "",
                    "servers": [
                        {"name": "test-server", "command": ["python", "-m", "some_server"], "cwd": None, "env": {}}
                    ],
                }

                # 1. 保存初始配置
                client.put("/api/model-config", json=sample_model)
                client.put("/api/mcp-config", json=sample_mcp)

                # 2. 导出
                export_resp = client.post("/api/config/export", json={"exportModels": True, "exportMcp": True})
                exported_data = export_resp.json()["data"]

                # 3. 修改配置（模拟另一实例有不同的配置）
                new_config = json.loads(json.dumps(sample_model))
                new_config["defaultProviderId"] = "other-provider"
                new_config["providers"] = [
                    {
                        "id": "other-provider",
                        "name": "Other",
                        "baseUrl": "http://other:8000/v1",
                        "apiKey": "",
                        "apiKeyEnvVar": "",
                        "timeout": 30.0,
                        "jsonMode": False,
                        "models": [{"id": "other-model", "name": "Other", "model": "other-model", "flash": False}],
                    }
                ]
                new_config["defaultModelId"] = "other-model"
                client.put("/api/model-config", json=new_config)

                # 4. 导入之前导出的配置
                import_resp = client.post(
                    "/api/config/import",
                    json={"payload": exported_data, "importModels": True, "importMcp": True},
                )
                self.assertEqual(import_resp.status_code, 200)

                # 5. 验证配置已恢复为导出时的状态
                model_resp = client.get("/api/model-config")
                self.assertEqual(model_resp.json()["defaultProviderId"], "test-provider")