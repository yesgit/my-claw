"""Email 工具单元测试。

测试 EmailTool 的 describe/execute、config 的 CRUD、imap_client 的解析逻辑。
不依赖真实 IMAP 服务器，使用 mock 替代网络调用。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.models import OperationRequest
from backend.tools.email.tool import EmailTool


# ==================== EmailTool.describe ====================


class TestEmailToolDescribe:
    """测试 EmailTool.describe() 返回结构。"""

    def test_describe_structure(self):
        tool = EmailTool()
        desc = tool.describe()
        assert desc["tool"] == "email"
        assert "actions" in desc
        action_names = [a["name"] for a in desc["actions"]]
        assert "check_new_emails" in action_names
        assert "search_emails" in action_names
        assert "read_email" in action_names
        assert "send_email" in action_names
        assert "configure" in action_names


class TestEmailToolExecuteInvalidAction:
    """测试无效 action 抛出异常。"""

    def test_invalid_action(self):
        tool = EmailTool()
        op = OperationRequest(tool="email", action="invalid_action", resource="*", risk="low")
        with pytest.raises(ValueError, match="不支持的 action"):
            tool.execute(op)


class TestEmailToolExecuteListAccounts:
    """测试 list_accounts action。"""

    def test_list_accounts(self):
        tool = EmailTool()
        op = OperationRequest(tool="email", action="list_accounts", resource="*", risk="low")
        result = tool.execute(op)
        assert result["ok"] is True
        assert "accounts" in result


# ==================== Config CRUD 测试 ====================


class TestConfigCRUD:
    """测试 config 模块的 CRUD 函数。"""

    def test_add_and_list_accounts(self, tmp_path):
        cfg_file = tmp_path / "email_config.json"
        cfg_file.write_text('{"accounts": []}', encoding="utf-8")

        with patch("backend.tools.email.config.EMAIL_CONFIG_PATH", cfg_file), \
             patch("backend.tools.email.config._set_password", return_value=True):
            from backend.tools.email.config import add_account, list_accounts

            result = add_account(
                name="测试邮箱",
                imap_host="imap.test.com",
                email_address="user@test.com",
                password="pass123",
            )
            assert result["ok"] is True
            assert result["account"]["name"] == "测试邮箱"

            accounts = list_accounts()
            assert len(accounts) == 1
            assert accounts[0]["email"] == "user@test.com"

    def test_add_duplicate_email(self, tmp_path):
        cfg_file = tmp_path / "email_config.json"
        cfg_file.write_text('{"accounts": []}', encoding="utf-8")

        with patch("backend.tools.email.config.EMAIL_CONFIG_PATH", cfg_file), \
             patch("backend.tools.email.config._set_password", return_value=True):
            from backend.tools.email.config import add_account

            r1 = add_account(name="A", imap_host="imap.test.com", email_address="dup@test.com", password="p")
            assert r1["ok"] is True

            r2 = add_account(name="B", imap_host="imap.test.com", email_address="dup@test.com", password="p")
            assert r2["ok"] is False
            assert "已存在" in r2.get("error", "")

    def test_delete_account(self, tmp_path):
        cfg_file = tmp_path / "email_config.json"
        cfg_file.write_text('{"accounts": []}', encoding="utf-8")

        with patch("backend.tools.email.config.EMAIL_CONFIG_PATH", cfg_file), \
             patch("backend.tools.email.config._set_password", return_value=True), \
             patch("backend.tools.email.config._delete_password", return_value=True):
            from backend.tools.email.config import add_account, delete_account

            acct = add_account(name="D", imap_host="imap.test.com", email_address="del@t.com", password="p")
            assert acct["ok"] is True

            result = delete_account(acct["account"]["id"])
            assert result["ok"] is True


# ==================== IMAPClient 解析测试 ====================


class TestIMAPClientParsing:
    """测试 imap_client 的邮件解析辅助方法。"""

    def test_extract_body_text(self):
        """测试 _extract_body 提取文本正文。"""
        from backend.tools.email.imap_client import _extract_body
        from email.message import EmailMessage

        msg = EmailMessage()
        msg.set_content("这是正文内容")

        body = _extract_body(msg)
        assert "正文" in body

    def test_decode_header_value(self):
        """测试 _decode_header_value 解码编码头部。"""
        from backend.tools.email.imap_client import _decode_header_value

        result = _decode_header_value("plain text")
        assert result == "plain text"

    def test_parse_email_message(self):
        """测试 _parse_email_message 完整解析。"""
        from backend.tools.email.imap_client import _parse_email_message
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = "测试主题"
        msg["From"] = "sender@test.com"
        msg["To"] = "recv@test.com"
        msg["Date"] = "Wed, 28 May 2026 10:00:00 +0800"
        msg.set_content("正文内容")

        result = _parse_email_message(msg, uid="42", include_body=True)
        assert result["uid"] == "42"
        assert result["subject"] == "测试主题"
        assert result["from"] == "sender@test.com"
        assert "正文" in result.get("body", "")


# ==================== test_connection mock ====================


class TestConnectionTest:
    """测试 test_connection 函数。"""

    def test_connection_success(self):
        """测试 IMAP 连接成功（mock imaplib）。"""
        mock_imap = MagicMock()
        mock_imap.login.return_value = ("OK", [b"LOGIN completed"])
        mock_imap.select.return_value = ("OK", [b"1"])
        mock_imap.search.return_value = ("OK", [b"1 2 3"])
        mock_imap.logout.return_value = ("OK", [b"Logging out"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
            from backend.tools.email.config import test_connection

            result = test_connection(
                imap_host="imap.test.com",
                imap_port=993,
                email_address="u@t.com",
                password="pass",
                use_ssl=True,
            )
            assert result["ok"] is True

    def test_connection_failure(self):
        """测试 IMAP 连接失败。"""
        with patch("imaplib.IMAP4_SSL", side_effect=Exception("Connection refused")):
            from backend.tools.email.config import test_connection

            result = test_connection(
                imap_host="bad.host",
                imap_port=993,
                email_address="u@t.com",
                password="pass",
                use_ssl=True,
            )
            assert result["ok"] is False
            assert "Connection refused" in result.get("error", "")


# ==================== ToolRouter 注册测试 ====================


class TestToolRouterRegistration:
    """测试 EmailTool 已注册到 ToolRouter。"""

    def test_email_in_tool_list(self):
        """确保 email 出现在工具列表中。"""
        from backend.tool_router.router import ToolRouter
        router = ToolRouter()
        tools = router.list_tools()
        tool_names = [t["tool"] for t in tools]
        assert "email" in tool_names