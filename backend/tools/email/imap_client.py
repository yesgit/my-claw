"""IMAP/SMTP 邮件客户端。

基于 Python 标准库 imaplib / smtplib / email 实现，无需额外依赖。
"""
from __future__ import annotations

import email
import email.header
import imaplib
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

logger = logging.getLogger(__name__)


def _decode_header_value(raw: str) -> str:
    """解码邮件头部字段（支持编码词）。"""
    if not raw:
        return ""
    decoded_parts = email.header.decode_header(raw)
    parts = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            charset = charset or "utf-8"
            try:
                parts.append(part.decode(charset, errors="replace"))
            except (LookupError, UnicodeDecodeError):
                parts.append(part.decode("utf-8", errors="replace"))
        else:
            parts.append(part)
    return "".join(parts)


def _extract_body(msg: email.message.Message) -> str:
    """提取邮件正文（优先纯文本，回退 HTML）。"""
    if msg.is_multipart():
        text_body = ""
        html_body = ""
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                continue
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        text_body = payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        text_body = payload.decode("utf-8", errors="replace")
            elif content_type == "text/html" and not text_body:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        html_body = payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        html_body = payload.decode("utf-8", errors="replace")
        return text_body or html_body
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                return payload.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                return payload.decode("utf-8", errors="replace")
    return ""


def _extract_attachments(msg: email.message.Message) -> list[dict[str, str]]:
    """提取附件列表（仅返回文件名和类型，不下载内容）。"""
    attachments = []
    for part in msg.walk():
        disposition = str(part.get("Content-Disposition", ""))
        if "attachment" in disposition:
            filename = part.get_filename()
            if filename:
                filename = _decode_header_value(filename)
            else:
                filename = "unnamed_attachment"
            content_type = part.get_content_type() or "application/octet-stream"
            attachments.append({
                "filename": filename,
                "content_type": content_type,
            })
    return attachments


def _parse_email_message(
    msg: email.message.Message,
    uid: str = "",
    include_body: bool = False,
) -> dict[str, Any]:
    """解析邮件消息为结构化字典。"""
    subject = _decode_header_value(msg.get("Subject", ""))
    from_raw = msg.get("From", "")
    to_raw = msg.get("To", "")
    date_raw = msg.get("Date", "")

    result: dict[str, Any] = {
        "uid": uid,
        "subject": subject,
        "from": _decode_header_value(from_raw),
        "to": _decode_header_value(to_raw),
        "date": date_raw,
    }

    if include_body:
        result["body"] = _extract_body(msg)
        result["attachments"] = _extract_attachments(msg)

    return result


class EmailClient:
    """IMAP 邮件客户端。"""

    def __init__(
        self,
        imap_host: str,
        imap_port: int = 993,
        email_address: str = "",
        password: str = "",
        use_ssl: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._imap_host = imap_host
        self._imap_port = imap_port
        self._email = email_address
        self._password = password
        self._use_ssl = use_ssl
        self._timeout = timeout
        self._conn: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None

    def connect(self) -> bool:
        """连接并登录 IMAP 服务器。"""
        try:
            if self._use_ssl:
                self._conn = imaplib.IMAP4_SSL(self._imap_host, self._imap_port, timeout=self._timeout)
            else:
                self._conn = imaplib.IMAP4(self._imap_host, self._imap_port, timeout=self._timeout)
            self._conn.login(self._email, self._password)
            return True
        except imaplib.IMAP4.error as exc:
            logger.error("IMAP 登录失败: %s", exc)
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error("IMAP 连接失败: %s", exc)
            return False

    def disconnect(self) -> None:
        """断开 IMAP 连接。"""
        if self._conn:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._conn.logout()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None

    def list_folders(self) -> list[dict[str, str]]:
        """列出邮箱文件夹。"""
        if not self._conn:
            return []
        try:
            status, folders = self._conn.list()
            if status != "OK":
                return []
            result = []
            for folder in folders:
                if folder:
                    parts = folder.decode("utf-8", errors="replace")
                    # 格式: (\\HasNoChildren) "/" "INBOX"
                    try:
                        folder_name = parts.split('"/')[-1].strip().strip('"')
                    except (IndexError, ValueError):
                        folder_name = parts
                    result.append({"name": folder_name, "raw": parts})
            return result
        except Exception as exc:  # noqa: BLE001
            logger.error("列出文件夹失败: %s", exc)
            return []

    def check_new_emails(
        self,
        folder: str = "INBOX",
        since_uid: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """检查新邮件。

        Args:
            folder: 文件夹名，默认 INBOX。
            since_uid: 只返回此 UID 之后的邮件（用于增量检查）。
            limit: 最多返回的邮件数量。

        Returns:
            包含新邮件摘要列表的字典。
        """
        if not self._conn:
            return {"ok": False, "error": "未连接 IMAP 服务器"}

        try:
            status, _ = self._conn.select(folder, readonly=True)
            if status != "OK":
                return {"ok": False, "error": f"无法打开文件夹: {folder}"}

            if since_uid:
                # 增量检查：获取指定 UID 之后的邮件
                status, data = self._conn.uid("search", None, "UID", f"{since_uid}:*")
            else:
                # 获取最近的邮件（UID 模式，以便后续 uid fetch）
                status, data = self._conn.uid("search", None, "ALL")

            if status != "OK" or not data or not data[0]:
                return {"ok": True, "emails": [], "count": 0}

            uid_list = data[0].split()
            # 排除 since_uid 本身
            if since_uid:
                uid_list = [uid for uid in uid_list if uid.decode() != since_uid]

            # 取最新的 limit 封（UID 通常递增，直接取末尾）
            uid_list = uid_list[-limit:]

            emails: list[dict[str, Any]] = []
            for uid in uid_list:
                status, msg_data = self._conn.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE TO)])")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                parsed = _parse_email_message(msg, uid=uid.decode())
                emails.append(parsed)

            return {"ok": True, "emails": emails, "count": len(emails)}

        except Exception as exc:  # noqa: BLE001
            logger.error("检查新邮件失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def read_email(
        self,
        uid: str,
        folder: str = "INBOX",
    ) -> dict[str, Any]:
        """读取指定邮件的完整内容。

        Args:
            uid: 邮件 UID。
            folder: 文件夹名。

        Returns:
            包含完整邮件内容的字典。
        """
        if not self._conn:
            return {"ok": False, "error": "未连接 IMAP 服务器"}

        try:
            status, _ = self._conn.select(folder, readonly=True)
            if status != "OK":
                return {"ok": False, "error": f"无法打开文件夹: {folder}"}

            status, msg_data = self._conn.uid("fetch", uid, "(BODY.PEEK[])")
            if status != "OK" or not msg_data or not msg_data[0]:
                return {"ok": False, "error": f"邮件不存在: UID {uid}"}

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            parsed = _parse_email_message(msg, uid=uid, include_body=True)

            return {"ok": True, "email": parsed}

        except Exception as exc:  # noqa: BLE001
            logger.error("读取邮件失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def search_emails(
        self,
        criteria: dict[str, str],
        folder: str = "INBOX",
        limit: int = 20,
    ) -> dict[str, Any]:
        """搜索邮件。

        Args:
            criteria: 搜索条件，支持 from、subject、since（日期，DD-Mon-YYYY）、to。
            folder: 文件夹名。
            limit: 最多返回数量。

        Returns:
            匹配的邮件摘要列表。返回的 uid 可用于 read_email。
        """
        if not self._conn:
            return {"ok": False, "error": "未连接 IMAP 服务器"}

        try:
            status, _ = self._conn.select(folder, readonly=True)
            if status != "OK":
                return {"ok": False, "error": f"无法打开文件夹: {folder}"}

            # 构建 IMAP 搜索条件
            search_parts: list[bytes] = []
            if criteria.get("from"):
                search_parts.extend([b"FROM", criteria["from"].encode("utf-8")])
            if criteria.get("subject"):
                search_parts.extend([b"SUBJECT", criteria["subject"].encode("utf-8")])
            if criteria.get("since"):
                search_parts.extend([b"SINCE", criteria["since"].encode("utf-8")])
            if criteria.get("to"):
                search_parts.extend([b"TO", criteria["to"].encode("utf-8")])

            if not search_parts:
                search_parts = [b"ALL"]

            # 使用 UID 搜索，保证返回的 uid 可用于 read_email
            status, data = self._conn.uid("search", *search_parts)
            if status != "OK" or not data or not data[0]:
                return {"ok": True, "emails": [], "count": 0}

            uid_list = data[0].split()[-limit:]

            emails: list[dict[str, Any]] = []
            for uid in uid_list:
                status, msg_data = self._conn.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE TO)])")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                parsed = _parse_email_message(msg, uid=uid.decode())
                emails.append(parsed)

            return {"ok": True, "emails": emails, "count": len(emails)}

        except Exception as exc:  # noqa: BLE001
            logger.error("搜索邮件失败: %s", exc)
            return {"ok": False, "error": str(exc)}


def send_email_smtp(
    smtp_host: str,
    smtp_port: int,
    email_address: str,
    password: str,
    to: str,
    subject: str,
    body: str,
    use_ssl: bool = True,
    cc: str = "",
) -> dict[str, Any]:
    """通过 SMTP 发送邮件。

    Args:
        smtp_host: SMTP 服务器地址。
        smtp_port: SMTP 端口。
        email_address: 发件人邮箱。
        password: 密码。
        to: 收件人（多个用逗号分隔）。
        subject: 邮件主题。
        body: 邮件正文。
        use_ssl: 是否使用 SSL。
        cc: 抄送（多个用逗号分隔）。

    Returns:
        发送结果字典。
    """
    try:
        msg = MIMEMultipart()
        msg["From"] = email_address
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc

        msg.attach(MIMEText(body, "plain", "utf-8"))

        recipients = [addr.strip() for addr in to.split(",")]
        if cc:
            recipients.extend(addr.strip() for addr in cc.split(","))

        conn = None
        try:
            if use_ssl:
                conn = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
            else:
                conn = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
                conn.starttls()

            conn.login(email_address, password)
            conn.sendmail(email_address, recipients, msg.as_string())

            return {"ok": True, "message": f"邮件已发送至 {to}"}
        finally:
            if conn:
                try:
                    conn.quit()
                except Exception:  # noqa: BLE001
                    pass

    except smtplib.SMTPAuthenticationError:
        return {"ok": False, "error": "SMTP 认证失败"}
    except smtplib.SMTPRecipientsRefused as exc:
        return {"ok": False, "error": f"收件人被拒绝: {exc}"}
    except Exception as exc:  # noqa: BLE001
        logger.error("发送邮件失败: %s", exc)
        return {"ok": False, "error": str(exc)}
