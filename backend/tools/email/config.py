"""邮箱账户配置管理。

非敏感信息（服务器地址、邮箱地址等）存储在 data/email_config.json。
密码通过 keyring 安全存储在系统密钥链中（service="myclaw.email"）。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

_KEYRING_SERVICE = "myclaw.email"

# 配置文件路径（支持 PyInstaller 打包）
_BUNDLE_DIR = Path(os.environ.get("MYCLAW_BUNDLE_DIR", Path(__file__).resolve().parents[3]))
_DATA_DIR = Path(os.environ.get("MYCLAW_DATA_DIR", _BUNDLE_DIR / "data"))
EMAIL_CONFIG_PATH = _DATA_DIR / "email_config.json"


def _load_config() -> dict[str, Any]:
    """加载邮箱配置文件。"""
    if not EMAIL_CONFIG_PATH.exists():
        return {"accounts": []}
    try:
        return json.loads(EMAIL_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("邮箱配置文件读取失败: %s", exc)
        return {"accounts": []}


def _save_config(config: dict[str, Any]) -> None:
    """保存邮箱配置文件。"""
    EMAIL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    EMAIL_CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _get_password(email_address: str) -> str | None:
    """从系统密钥链获取密码。"""
    try:
        import keyring  # noqa: PLC0415
        return keyring.get_password(_KEYRING_SERVICE, email_address)
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyring 获取密码失败: %s", exc)
        return None


def _set_password(email_address: str, password: str) -> bool:
    """将密码存储到系统密钥链。"""
    try:
        import keyring  # noqa: PLC0415
        keyring.set_password(_KEYRING_SERVICE, email_address, password)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("keyring 存储密码失败: %s", exc)
        return False


def _delete_password(email_address: str) -> bool:
    """从系统密钥链删除密码。"""
    try:
        import keyring  # noqa: PLC0415
        keyring.delete_password(_KEYRING_SERVICE, email_address)
        return True
    except keyring.errors.PasswordDeleteError:
        return True  # 密码不存在也算成功
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyring 删除密码失败: %s", exc)
        return False


def list_accounts() -> list[dict[str, Any]]:
    """列出所有已配置的邮箱账户（不返回密码）。"""
    config = _load_config()
    accounts = []
    for acct in config.get("accounts", []):
        accounts.append({
            "id": acct.get("id", ""),
            "name": acct.get("name", ""),
            "imap_host": acct.get("imap_host", ""),
            "imap_port": acct.get("imap_port", 993),
            "smtp_host": acct.get("smtp_host", ""),
            "smtp_port": acct.get("smtp_port", 465),
            "email": acct.get("email", ""),
            "use_ssl": acct.get("use_ssl", True),
            "enabled": acct.get("enabled", True),
            "has_password": _get_password(acct.get("email", "")) is not None,
        })
    return accounts


def get_account(account_id: str) -> dict[str, Any] | None:
    """获取指定账户配置（不含密码）。"""
    config = _load_config()
    for acct in config.get("accounts", []):
        if acct.get("id") == account_id:
            return {
                "id": acct["id"],
                "name": acct.get("name", ""),
                "imap_host": acct.get("imap_host", ""),
                "imap_port": acct.get("imap_port", 993),
                "smtp_host": acct.get("smtp_host", ""),
                "smtp_port": acct.get("smtp_port", 465),
                "email": acct.get("email", ""),
                "use_ssl": acct.get("use_ssl", True),
                "enabled": acct.get("enabled", True),
                "has_password": _get_password(acct.get("email", "")) is not None,
            }
    return None


def get_account_with_password(account_id: str) -> dict[str, Any] | None:
    """获取指定账户配置（含密码），仅供内部连接使用。"""
    config = _load_config()
    for acct in config.get("accounts", []):
        if acct.get("id") == account_id:
            password = _get_password(acct.get("email", ""))
            if password is None:
                return None
            return {
                "id": acct["id"],
                "name": acct.get("name", ""),
                "imap_host": acct.get("imap_host", ""),
                "imap_port": acct.get("imap_port", 993),
                "smtp_host": acct.get("smtp_host", ""),
                "smtp_port": acct.get("smtp_port", 465),
                "email": acct.get("email", ""),
                "password": password,
                "use_ssl": acct.get("use_ssl", True),
                "enabled": acct.get("enabled", True),
            }
    return None


def add_account(
    name: str,
    imap_host: str,
    email_address: str,
    password: str,
    imap_port: int = 993,
    smtp_host: str = "",
    smtp_port: int = 465,
    use_ssl: bool = True,
) -> dict[str, Any]:
    """添加邮箱账户。

    Args:
        name: 账户显示名称。
        imap_host: IMAP 服务器地址。
        email_address: 邮箱地址。
        password: 邮箱密码或授权码。
        imap_port: IMAP 端口，默认 993。
        smtp_host: SMTP 服务器地址（可选）。
        smtp_port: SMTP 端口，默认 465。
        use_ssl: 是否使用 SSL，默认 True。

    Returns:
        添加后的账户信息（不含密码）。
    """
    config = _load_config()

    # 检查邮箱地址是否已存在
    for acct in config.get("accounts", []):
        if acct.get("email") == email_address:
            return {"ok": False, "error": f"邮箱地址 {email_address} 已存在"}

    account_id = str(uuid4())
    account = {
        "id": account_id,
        "name": name,
        "imap_host": imap_host,
        "imap_port": imap_port,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "email": email_address,
        "use_ssl": use_ssl,
        "enabled": True,
    }

    # 存密码到 keyring
    if not _set_password(email_address, password):
        return {"ok": False, "error": "密码存储到系统密钥链失败"}

    config.setdefault("accounts", []).append(account)
    _save_config(config)

    logger.info("邮箱账户已添加: %s (%s)", name, email_address)
    return {"ok": True, "account": {**account, "has_password": True}}


def update_account(
    account_id: str,
    name: str | None = None,
    imap_host: str | None = None,
    imap_port: int | None = None,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    email_address: str | None = None,
    password: str | None = None,
    use_ssl: bool | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """更新邮箱账户配置。"""
    config = _load_config()

    for acct in config.get("accounts", []):
        if acct.get("id") == account_id:
            old_email = acct.get("email", "")

            if name is not None:
                acct["name"] = name
            if imap_host is not None:
                acct["imap_host"] = imap_host
            if imap_port is not None:
                acct["imap_port"] = imap_port
            if smtp_host is not None:
                acct["smtp_host"] = smtp_host
            if smtp_port is not None:
                acct["smtp_port"] = smtp_port
            if use_ssl is not None:
                acct["use_ssl"] = use_ssl
            if enabled is not None:
                acct["enabled"] = enabled
            if email_address is not None and email_address != old_email:
                # 邮箱地址变更，删除旧 keyring 条目
                _delete_password(old_email)
                acct["email"] = email_address

            # 更新密码（如果提供了新密码）
            if password is not None:
                target_email = email_address or old_email
                if not _set_password(target_email, password):
                    return {"ok": False, "error": "密码更新失败"}

            _save_config(config)
            logger.info("邮箱账户已更新: %s", account_id)
            return {"ok": True, "account": {**acct, "has_password": True}}

    return {"ok": False, "error": f"账户不存在: {account_id}"}


def delete_account(account_id: str) -> dict[str, Any]:
    """删除邮箱账户。"""
    config = _load_config()

    accounts = config.get("accounts", [])
    to_delete = None
    remaining = []
    for acct in accounts:
        if acct.get("id") == account_id:
            to_delete = acct
        else:
            remaining.append(acct)

    if to_delete is None:
        return {"ok": False, "error": f"账户不存在: {account_id}"}

    # 从 keyring 删除密码
    _delete_password(to_delete.get("email", ""))

    config["accounts"] = remaining
    _save_config(config)

    logger.info("邮箱账户已删除: %s (%s)", to_delete.get("name"), to_delete.get("email"))
    return {"ok": True, "message": f"账户 {to_delete.get('name', '')} 已删除"}


def test_connection(
    imap_host: str,
    imap_port: int,
    email_address: str,
    password: str,
    use_ssl: bool = True,
) -> dict[str, Any]:
    """测试 IMAP 连接是否正常。"""
    import imaplib  # noqa: PLC0415

    conn = None
    try:
        if use_ssl:
            conn = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=30)
        else:
            conn = imaplib.IMAP4(imap_host, imap_port, timeout=30)

        conn.login(email_address, password)
        conn.select("INBOX", readonly=True)
        status, data = conn.search(None, "ALL")
        mail_count = len(data[0].split()) if data and data[0] else 0
        conn.logout()
        conn = None

        return {
            "ok": True,
            "message": f"连接成功，收件箱共有 {mail_count} 封邮件",
            "mail_count": mail_count,
        }
    except imaplib.IMAP4.error as exc:
        return {"ok": False, "error": f"IMAP 连接失败: {exc}"}
    except TimeoutError:
        return {"ok": False, "error": "连接超时，请检查服务器地址和端口"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"连接失败: {exc}"}
    finally:
        if conn:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass


def test_smtp_connection(
    smtp_host: str,
    smtp_port: int,
    email_address: str,
    password: str,
    use_ssl: bool = True,
) -> dict[str, Any]:
    """测试 SMTP 连接是否正常。"""
    import smtplib  # noqa: PLC0415

    conn = None
    try:
        if use_ssl:
            conn = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        else:
            conn = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            conn.starttls()

        conn.login(email_address, password)
        conn.quit()
        conn = None

        return {"ok": True, "message": "SMTP 连接成功"}
    except smtplib.SMTPAuthenticationError:
        return {"ok": False, "error": "SMTP 认证失败，请检查邮箱地址和密码"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"SMTP 连接失败: {exc}"}
    finally:
        if conn:
            try:
                conn.quit()
            except Exception:  # noqa: BLE001
                pass
