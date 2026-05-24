"""视觉模型调用模块。

将截图发送给视觉大模型（如 qwen），提取聊天消息结构化数据。
配置从外部传入，不硬编码。
"""
from __future__ import annotations

import base64
import io
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_MODEL = "qwen3.6-plus"

# 读取消息的默认 prompt
READ_MESSAGES_PROMPT = (
    "这是一张企业微信聊天窗口的截图。\n"
    "请仔细识别图中每一条消息，特别注意：\n"
    "- 发送人姓名通常显示在消息气泡上方的灰色小字\n"
    "- 时间戳显示在消息之间居中的灰色小字，格式如\"5/20 13:34:38\"\n"
    "要求：\n"
    "1. 按时间顺序列出每条消息\n"
    "2. 必须标注每条消息的发送人姓名\n"
    "3. 完整保留消息内容\n"
    "4. 用JSON输出：{\"messages\": [{\"time\": \"...\", \"sender\": \"...\", \"content\": \"...\"}]}"
)

# 识别聊天列表的 prompt
LIST_CHATS_PROMPT = (
    "这是企业微信左侧消息列表的截图。\n"
    "请识别图中显示的每个聊天项（群聊或私聊），提取：\n"
    "- 聊天名称\n"
    "- 最新消息摘要（如果可见）\n"
    "- 未读数量（如果有标记）\n"
    "用JSON输出：{\"chats\": [{\"name\": \"...\", \"summary\": \"...\", \"unread\": 0}]}"
)


def compress_image(image_path: str, max_width: int = 1200, quality: int = 85) -> bytes:
    """压缩图片为 JPEG bytes。

    Args:
        image_path: 图片文件路径。
        max_width: 最大宽度，超过则等比缩放。
        quality: JPEG 质量（1-100）。

    Returns:
        JPEG 格式的 bytes。
    """
    from PIL import Image

    img = Image.open(image_path)
    if img.width > max_width:
        new_h = int(img.height * max_width / img.width)
        img = img.resize((max_width, new_h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def call_vision_api(
    image_path: str,
    prompt: str,
    api_url: str = DEFAULT_API_URL,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    timeout: int = 120,
    max_retries: int = 3,
) -> str | None:
    """调用视觉模型 API 分析图片。

    Args:
        image_path: 截图文件路径。
        prompt: 发送给模型的提示词。
        api_url: API 地址。
        api_key: API 密钥。
        model: 模型名称。
        timeout: 请求超时秒数。
        max_retries: 最大重试次数。

    Returns:
        模型返回的文本内容，失败返回 None。
    """
    import requests

    logger.info("视觉模型调用: %s (%s)", model, image_path)

    # 压缩图片
    img_bytes = compress_image(image_path)
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    logger.info("图片压缩: %d -> %d bytes", os.path.getsize(image_path), len(img_bytes))

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            ],
        }
    ]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "enable_thinking": False,
    }

    for retry in range(max_retries):
        try:
            resp = requests.post(
                api_url,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
            )

            if resp.status_code == 429:
                wait = 30 * (retry + 1)
                logger.warning("429 限流，等待 %ds 后重试 (%d/%d)", wait, retry + 1, max_retries)
                time.sleep(wait)
                continue

            resp.raise_for_status()
            result = resp.json()
            content = result["choices"][0]["message"]["content"]
            logger.info("视觉模型返回: %d 字", len(content))
            return content

        except requests.exceptions.Timeout:
            logger.warning("超时，重试 (%d/%d)", retry + 1, max_retries)
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP 错误: %s", e)
            try:
                logger.error("响应: %s", e.response.text[:500])
            except Exception:
                pass
            break
        except Exception as e:
            logger.error("视觉模型调用失败: %s", e)
            break

    return None


def parse_messages_from_vision(text: str) -> list[dict[str, str]]:
    """从视觉模型返回的文本中解析消息列表。

    Args:
        text: 视觉模型返回的 JSON 文本（可能包含 markdown 代码块）。

    Returns:
        消息列表 [{"time": ..., "sender": ..., "content": ...}, ...]
    """
    import json
    import re

    # 尝试提取 JSON 代码块
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        json_str = text.strip()

    try:
        data = json.loads(json_str)
        if isinstance(data, dict) and "messages" in data:
            return data["messages"]
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # 尝试宽松匹配
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            data = json.loads(text[brace_start : brace_end + 1])
            if isinstance(data, dict) and "messages" in data:
                return data["messages"]
        except json.JSONDecodeError:
            pass

    # 容错解析：尝试从非结构化文本中按行提取消息
    fallback = _parse_messages_from_plain_text(text)
    if fallback:
        logger.info("通过行级容错解析提取到 %d 条消息", len(fallback))
        return fallback

    logger.warning("无法从视觉模型返回中解析 JSON")
    return []


def _parse_messages_from_plain_text(text: str) -> list[dict[str, str]]:
    """从容错文本中按行提取消息。

    支持的格式：
    - "发送人: 内容" 或 "发送人：内容"
    - "[时间] 发送人: 内容"
    - "时间 发送人 内容"（空格分隔）

    Returns:
        消息列表，空列表表示无法提取。
    """
    import re

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return []

    messages: list[dict[str, str]] = []

    # 模式 1: [时间] 发送人: 内容  或  时间 发送人: 内容
    pat_time_sender = re.compile(
        r"(?:\[([^\]]+)\]\s*)?"          # 可选的 [时间]
        r"(\S.{0,20}?)"                   # 发送人（非贪婪，最多 20 字符）
        r"[:\uff1a]\s*"                   # 冒号（半角/全角）
        r"(.+)",                          # 内容
    )

    # 模式 2: - 发送人: 内容（列表项）
    pat_list_item = re.compile(
        r"[-*\u2022]\s*"                  # 列表标记
        r"(\S.{0,20}?)"                   # 发送人
        r"[:\uff1a]\s*"                   # 冒号
        r"(.+)",                          # 内容
    )

    for line in lines:
        # 跳过纯时间行（居中的时间戳）
        if re.match(r"^\d{1,4}[/-]\d{1,2}[/-]?\d{0,2}\s+\d{1,2}:\d{2}", line):
            continue
        # 跳过 JSON/代码块标记
        if line in ("```", "```json", "{", "}", '"]'):
            continue
        # 跳过过短行
        if len(line) < 3:
            continue

        m = pat_time_sender.match(line)
        if m:
            time_val = m.group(1) or ""
            sender = m.group(2).strip()
            content = m.group(3).strip()
            if content:
                msg: dict[str, str] = {"sender": sender, "content": content}
                if time_val:
                    msg["time"] = time_val
                messages.append(msg)
            continue

        m2 = pat_list_item.match(line)
        if m2:
            sender = m2.group(1).strip()
            content = m2.group(2).strip()
            if content:
                messages.append({"sender": sender, "content": content})
            continue

    return messages


def parse_chats_from_vision(text: str) -> list[dict[str, Any]]:
    """从视觉模型返回的文本中解析聊天列表。

    Args:
        text: 视觉模型返回的 JSON 文本（可能包含 markdown 代码块）。

    Returns:
        聊天列表 [{"name": ..., "summary": ..., "unread": ...}, ...]
    """
    import json
    import re

    # 尝试提取 JSON 代码块
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        json_str = text.strip()

    try:
        data = json.loads(json_str)
        if isinstance(data, dict) and "chats" in data:
            return data["chats"]
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # 宽松匹配
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            data = json.loads(text[brace_start : brace_end + 1])
            if isinstance(data, dict) and "chats" in data:
                return data["chats"]
        except json.JSONDecodeError:
            pass

    logger.warning("无法从视觉模型返回中解析聊天列表 JSON")
    return []
