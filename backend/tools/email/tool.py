"""邮件工具（MyClaw 工具规范）。

支持 Coremail 及其他邮箱服务商，通过 IMAP/SMTP 协议收发邮件。
密码通过 keyring 安全存储在系统密钥链中。

Actions:
    configure       (high) - 配置邮箱账户
    list_accounts   (low)  - 列出已配置的邮箱账户
    delete_account  (medium) - 删除邮箱账户配置
    test_connection (low)  - 测试邮箱连接
    check_new_emails (low)  - 检查收件箱新邮件
    read_email      (medium) - 读取指定邮件完整内容
    search_emails   (medium) - 按条件搜索邮件
    send_email      (high)  - 发送邮件
    list_folders    (low)  - 列出邮箱文件夹
"""
from __future__ import annotations

import logging
from typing import Any

from backend.models import OperationRequest
from backend.tools.email import config as email_config
from backend.tools.email.imap_client import EmailClient, send_email_smtp

logger = logging.getLogger(__name__)


class EmailTool:
    """邮件工具，支持 IMAP 收件 + SMTP 发件。"""

    tool_name = "email"
    description = "邮件工具，支持收发邮件、搜索邮件、监控新邮件等操作"

    supported_actions = {
        "configure": "high",
        "list_accounts": "low",
        "delete_account": "medium",
        "test_connection": "low",
        "check_new_emails": "low",
        "read_email": "medium",
        "search_emails": "medium",
        "send_email": "high",
        "list_folders": "low",
    }

    def describe(self) -> dict:
        """返回工具的标准自描述信息。"""
        actions = [
            {"name": action, "default_risk": risk}
            for action, risk in self.supported_actions.items()
        ]
        return {
            "tool": self.tool_name,
            "type": "local",
            "actions": actions,
            "input_schema": {
                "configure": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "账户显示名称"},
                        "imap_host": {"type": "string", "description": "IMAP 服务器地址"},
                        "imap_port": {"type": "integer", "description": "IMAP 端口，默认 993"},
                        "smtp_host": {"type": "string", "description": "SMTP 服务器地址"},
                        "smtp_port": {"type": "integer", "description": "SMTP 端口，默认 465"},
                        "email": {"type": "string", "description": "邮箱地址"},
                        "password": {"type": "string", "description": "邮箱密码或授权码"},
                        "use_ssl": {"type": "boolean", "description": "是否使用 SSL，默认 true"},
                    },
                    "required": ["name", "imap_host", "email", "password"],
                },
                "list_accounts": {
                    "type": "object",
                    "properties": {},
                },
                "delete_account": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "要删除的账户 ID"},
                    },
                    "required": ["account_id"],
                },
                "test_connection": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "要测试的账户 ID"},
                    },
                },
                "check_new_emails": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "邮箱账户 ID（多账户时必填）"},
                        "folder": {"type": "string", "description": "文件夹名，默认 INBOX"},
                        "limit": {"type": "integer", "description": "最多返回邮件数量，默认 20"},
                    },
                },
                "read_email": {
                    "type": "object",
                    "properties": {
                        "uid": {"type": "string", "description": "邮件 UID"},
                        "account_id": {"type": "string", "description": "邮箱账户 ID"},
                        "folder": {"type": "string", "description": "文件夹名，默认 INBOX"},
                    },
                    "required": ["uid"],
                },
                "search_emails": {
                    "type": "object",
                    "properties": {
                        "from": {"type": "string", "description": "发件人过滤"},
                        "subject": {"type": "string", "description": "主题关键词"},
                        "since": {"type": "string", "description": "起始日期（DD-Mon-YYYY）"},
                        "to": {"type": "string", "description": "收件人过滤"},
                        "account_id": {"type": "string", "description": "邮箱账户 ID"},
                        "folder": {"type": "string", "description": "文件夹名，默认 INBOX"},
                        "limit": {"type": "integer", "description": "最多返回数量，默认 20"},
                    },
                },
                "send_email": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "收件人（多个用逗号分隔）"},
                        "subject": {"type": "string", "description": "邮件主题"},
                        "body": {"type": "string", "description": "邮件正文"},
                        "cc": {"type": "string", "description": "抄送（多个用逗号分隔）"},
                        "account_id": {"type": "string", "description": "邮箱账户 ID"},
                    },
                    "required": ["to", "subject", "body"],
                },
                "list_folders": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "邮箱账户 ID"},
                    },
                },
            },
            "tool_name": self.tool_name,
            "description": self.description,
            "supported_actions": dict(self.supported_actions),
        }

    def execute(self, operation: OperationRequest) -> dict:
        """执行操作。"""
        if operation.action not in self.supported_actions:
            raise ValueError(f"email 不支持的 action: {operation.action}")

        try:
            action_map = {
                "configure": self._configure,
                "list_accounts": lambda _: self._list_accounts(),
                "delete_account": self._delete_account,
                "test_connection": self._test_connection,
                "check_new_emails": self._check_new_emails,
                "read_email": self._read_email,
                "search_emails": self._search_emails,
                "send_email": self._send_email,
                "list_folders": self._list_folders,
            }
            handler = action_map.get(operation.action)
            if handler:
                return handler(operation)
            # 不会到达这里（前面已校验 action）
            raise ValueError(f"未实现的 action: {operation.action}")  # pragma: no cover
        except Exception as exc:
            logger.exception("[Email] 执行 %s 失败", operation.action)
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # 账户管理
    # ------------------------------------------------------------------

    def _configure(self, operation: OperationRequest) -> dict:
        """配置邮箱账户。"""
        params = operation.params or {}
        name = str(params.get("name", "")).strip()
        imap_host = str(params.get("imap_host", "")).strip()
        email_address = str(params.get("email", "")).strip()
        password = str(params.get("password", ""))
        imap_port = int(params.get("imap_port", 993))
        smtp_host = str(params.get("smtp_host", "")).strip()
        smtp_port = int(params.get("smtp_port", 465))
        use_ssl = self._parse_bool(params.get("use_ssl", True))

        if not name:
            return {"ok": False, "error": "缺少 name 参数（账户名称）"}
        if not imap_host:
            return {"ok": False, "error": "缺少 imap_host 参数（IMAP 服务器地址）"}
        if not email_address:
            return {"ok": False, "error": "缺少 email 参数（邮箱地址）"}
        if not password:
            return {"ok": False, "error": "缺少 password 参数"}

        result = email_config.add_account(
            name=name,
            imap_host=imap_host,
            email_address=email_address,
            password=password,
            imap_port=imap_port,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            use_ssl=use_ssl,
        )
        return result

    def _list_accounts(self) -> dict:
        """列出已配置的邮箱账户。"""
        accounts = email_config.list_accounts()
        return {"ok": True, "accounts": accounts, "count": len(accounts)}

    def _delete_account(self, operation: OperationRequest) -> dict:
        """删除邮箱账户。"""
        params = operation.params or {}
        account_id = str(params.get("account_id", "")).strip()
        if not account_id:
            return {"ok": False, "error": "缺少 account_id 参数"}
        return email_config.delete_account(account_id)

    def _test_connection(self, operation: OperationRequest) -> dict:
        """测试邮箱连接。"""
        params = operation.params or {}
        account_id = str(params.get("account_id", "")).strip()

        if account_id:
            # 测试已配置的账户
            acct = email_config.get_account_with_password(account_id)
            if not acct:
                return {"ok": False, "error": "账户不存在或密码未设置"}
            return email_config.test_connection(
                imap_host=acct["imap_host"],
                imap_port=acct["imap_port"],
                email_address=acct["email"],
                password=acct["password"],
                use_ssl=acct.get("use_ssl", True),
            )

        # 测试临时传入的参数
        imap_host = str(params.get("imap_host", "")).strip()
        email_address = str(params.get("email", "")).strip()
        password = str(params.get("password", ""))
        imap_port = int(params.get("imap_port", 993))
        use_ssl = self._parse_bool(params.get("use_ssl", True))

        if not imap_host or not email_address or not password:
            return {"ok": False, "error": "需要 account_id 或 imap_host/email/password 参数"}

        return email_config.test_connection(
            imap_host=imap_host,
            imap_port=imap_port,
            email_address=email_address,
            password=password,
            use_ssl=use_ssl,
        )

    # ------------------------------------------------------------------
    # 邮件操作
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_bool(val: Any, default: bool = True) -> bool:
        """安全解析布尔值，兼容 LLM 传入的字符串 'false'/'true'。"""
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() not in ("false", "0", "no", "off")
        return default

    def _resolve_account(self, operation: OperationRequest) -> dict[str, Any] | None:
        """从操作请求中解析邮箱账户配置（跳过已禁用的账户）。"""
        params = operation.params or {}
        account_id = str(params.get("account_id", "")).strip()

        if not account_id:
            # 没有指定 account_id，使用第一个已启用的账户
            accounts = email_config.list_accounts()
            for acct in accounts:
                if acct.get("enabled", True):
                    account_id = acct["id"]
                    break
            if not account_id:
                return None

        acct = email_config.get_account_with_password(account_id)
        if acct and not acct.get("enabled", True):
            return None
        return acct

    def _check_new_emails(self, operation: OperationRequest) -> dict:
        """检查收件箱新邮件。"""
        params = operation.params or {}
        acct = self._resolve_account(operation)
        if not acct:
            return {
                "ok": False,
                "error": "没有可用的邮箱账户，请先使用 email.configure 配置邮箱",
            }

        folder = str(params.get("folder", "INBOX")).strip()
        limit = int(params.get("limit", 20))

        client = EmailClient(
            imap_host=acct["imap_host"],
            imap_port=acct["imap_port"],
            email_address=acct["email"],
            password=acct["password"],
            use_ssl=acct.get("use_ssl", True),
        )

        try:
            if not client.connect():
                return {"ok": False, "error": "无法连接 IMAP 服务器，请检查配置"}
            result = client.check_new_emails(folder=folder, limit=limit)
            result["account"] = acct["name"]
            return result
        finally:
            client.disconnect()

    def _read_email(self, operation: OperationRequest) -> dict:
        """读取指定邮件。"""
        params = operation.params or {}
        uid = str(params.get("uid", "")).strip()
        if not uid:
            return {"ok": False, "error": "缺少 uid 参数"}

        acct = self._resolve_account(operation)
        if not acct:
            return {"ok": False, "error": "没有可用的邮箱账户"}

        folder = str(params.get("folder", "INBOX")).strip()

        client = EmailClient(
            imap_host=acct["imap_host"],
            imap_port=acct["imap_port"],
            email_address=acct["email"],
            password=acct["password"],
            use_ssl=acct.get("use_ssl", True),
        )

        try:
            if not client.connect():
                return {"ok": False, "error": "无法连接 IMAP 服务器"}
            return client.read_email(uid=uid, folder=folder)
        finally:
            client.disconnect()

    def _search_emails(self, operation: OperationRequest) -> dict:
        """搜索邮件。"""
        params = operation.params or {}
        acct = self._resolve_account(operation)
        if not acct:
            return {"ok": False, "error": "没有可用的邮箱账户"}

        criteria = {}
        for key in ("from", "subject", "since", "to"):
            val = params.get(key)
            if val:
                criteria[key] = str(val)

        folder = str(params.get("folder", "INBOX")).strip()
        limit = int(params.get("limit", 20))

        client = EmailClient(
            imap_host=acct["imap_host"],
            imap_port=acct["imap_port"],
            email_address=acct["email"],
            password=acct["password"],
            use_ssl=acct.get("use_ssl", True),
        )

        try:
            if not client.connect():
                return {"ok": False, "error": "无法连接 IMAP 服务器"}
            result = client.search_emails(criteria=criteria, folder=folder, limit=limit)
            result["account"] = acct["name"]
            return result
        finally:
            client.disconnect()

    def _send_email(self, operation: OperationRequest) -> dict:
        """发送邮件。"""
        params = operation.params or {}
        to = str(params.get("to", "")).strip()
        subject = str(params.get("subject", "")).strip()
        body = str(params.get("body", "")).strip()
        cc = str(params.get("cc", "")).strip()

        if not to:
            return {"ok": False, "error": "缺少 to 参数（收件人）"}
        if not subject:
            return {"ok": False, "error": "缺少 subject 参数（邮件主题）"}
        if not body:
            return {"ok": False, "error": "缺少 body 参数（邮件正文）"}

        acct = self._resolve_account(operation)
        if not acct:
            return {"ok": False, "error": "没有可用的邮箱账户"}

        smtp_host = acct.get("smtp_host", "")
        smtp_port = acct.get("smtp_port", 465)

        if not smtp_host:
            return {"ok": False, "error": "账户未配置 SMTP 服务器，无法发送邮件"}

        return send_email_smtp(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            email_address=acct["email"],
            password=acct["password"],
            to=to,
            subject=subject,
            body=body,
            use_ssl=acct.get("use_ssl", True),
            cc=cc,
        )

    def _list_folders(self, operation: OperationRequest) -> dict:
        """列出邮箱文件夹。"""
        acct = self._resolve_account(operation)
        if not acct:
            return {"ok": False, "error": "没有可用的邮箱账户"}

        client = EmailClient(
            imap_host=acct["imap_host"],
            imap_port=acct["imap_port"],
            email_address=acct["email"],
            password=acct["password"],
            use_ssl=acct.get("use_ssl", True),
        )

        try:
            if not client.connect():
                return {"ok": False, "error": "无法连接 IMAP 服务器"}
            folders = client.list_folders()
            return {"ok": True, "folders": folders, "count": len(folders), "account": acct["name"]}
        finally:
            client.disconnect()