from __future__ import annotations

import json
import logging
import ssl
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib import error, request

logger = logging.getLogger(__name__)


class LLMClientError(RuntimeError):
    pass


@dataclass(slots=True)
class OpenAICompatibleConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float = 60.0
    json_mode: bool = True
    proxy_url: str | None = None  # 解析后的有效代理 URL，None 表示不走代理

    def __post_init__(self) -> None:
        self.api_key = _normalize_api_key(self.api_key)


def _normalize_api_key(api_key: str) -> str:
    normalized = (api_key or "").strip()
    if normalized.lower().startswith("bearer "):
        normalized = normalized[7:].strip()
    return normalized


@dataclass(slots=True)
class OpenAICompatibleChatClient:
    config: OpenAICompatibleConfig
    opener: Callable[..., Any] | None = None  # None 时自动根据 proxy_url 构建

    def __post_init__(self) -> None:
        if self.opener is not None:
            return
        if self.config.proxy_url:
            handler = request.ProxyHandler({"http": self.config.proxy_url, "https": self.config.proxy_url})
            self.opener = request.build_opener(handler).open
        else:
            self.opener = request.urlopen

    def chat(self, messages: list[dict[str, Any]], temperature: float = 0.0) -> str:
        if not self.config.api_key:
            raise LLMClientError("缺少 API Key，请填写以 sk- 开头的密钥")

        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
        }
        if self.config.json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"

        # [debug] 调试模式下记录 LLM 请求/响应详情
        try:
            from backend.debug import is_debug_enabled  # noqa: PLC0415
            if is_debug_enabled():
                logger.debug(
                    "[debug] LLM 请求 → %s | model=%s | messages=%d | temperature=%.2f",
                    endpoint, self.config.model, len(messages), temperature,
                )
        except Exception:  # noqa: BLE001
            pass
        req = request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
        )

        max_retries = 3
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                with self.opener(req, timeout=self.config.timeout) as resp:
                    raw_resp = resp.read().decode("utf-8")
                    payload = json.loads(raw_resp)
                text = self._extract_text(payload)
                try:
                    from backend.debug import is_debug_enabled  # noqa: PLC0415
                    if is_debug_enabled():
                        logger.debug(
                            "[debug] LLM 响应 ← %s | model=%s | response_chars=%d",
                            endpoint, self.config.model, len(text),
                        )
                        logger.debug("[debug] LLM 响应内容: %s", text[:500])
                except Exception:  # noqa: BLE001
                    pass
                return text
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                # 4xx 错误不重试（除 429 限流）
                if exc.code == 429 and attempt < max_retries:
                    last_exc = exc
                    wait = 2 ** attempt
                    logger.warning("LLM 限流 429，%ds 后重试 (%d/%d)", wait, attempt, max_retries)
                    time.sleep(wait)
                    continue
                raise LLMClientError(f"LLM HTTP error {exc.code}: {detail}") from exc
            except error.URLError as exc:
                last_exc = exc
                reason = exc.reason
                # SSL / 连接重置等瞬态错误可重试
                is_transient = isinstance(reason, (ssl.SSLError, ConnectionResetError, BrokenPipeError, OSError))
                if is_transient and attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning("LLM 网络瞬态错误 (%s)，%ds 后重试 (%d/%d)", reason, wait, attempt, max_retries)
                    time.sleep(wait)
                    continue
                raise LLMClientError(f"LLM 网络错误: {reason}") from exc

        raise LLMClientError(f"LLM 重试 {max_retries} 次后仍失败: {last_exc}") from last_exc

    def _extract_text(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMClientError("LLM 响应缺少 choices")

        first = choices[0]
        if not isinstance(first, dict):
            raise LLMClientError("LLM 响应 choices[0] 非对象")

        message = first.get("message")
        if not isinstance(message, dict):
            raise LLMClientError("LLM 响应 choices[0].message 非对象")

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            return self._map_tool_call_to_react_action(tool_calls)

        content = message.get("content")
        if not isinstance(content, str):
            raise LLMClientError("LLM 响应 content 不是字符串")
        return content

    def _map_tool_call_to_react_action(self, tool_calls: list[Any]) -> str:
        mapped_calls: list[dict[str, Any]] = []
        for idx, item in enumerate(tool_calls):
            if not isinstance(item, dict):
                raise LLMClientError(f"tool_calls[{idx}] 非对象")

            function = item.get("function")
            if not isinstance(function, dict):
                raise LLMClientError(f"tool_calls[{idx}].function 非对象")

            tool_call_id = item.get("id")
            name = function.get("name")
            raw_arguments = function.get("arguments", "{}")
            if not isinstance(name, str) or not name.strip():
                raise LLMClientError("tool_calls.function.name 不是有效字符串")
            if tool_call_id is not None and (not isinstance(tool_call_id, str) or not tool_call_id.strip()):
                raise LLMClientError("tool_calls.id 如果提供，必须是非空字符串")

            arguments: dict[str, Any]
            if isinstance(raw_arguments, str):
                try:
                    parsed = json.loads(raw_arguments)
                except json.JSONDecodeError as exc:
                    raise LLMClientError(f"tool_calls.function.arguments 不是有效 JSON: {exc}") from exc
                if not isinstance(parsed, dict):
                    raise LLMClientError("tool_calls.function.arguments 解析后必须是对象")
                arguments = parsed
            elif isinstance(raw_arguments, dict):
                arguments = raw_arguments
            else:
                raise LLMClientError("tool_calls.function.arguments 必须是 JSON 字符串或对象")

            call_payload = {"name": name, "arguments": arguments}
            if tool_call_id:
                call_payload["id"] = tool_call_id
            mapped_calls.append(call_payload)

        if len(mapped_calls) == 1:
            react_action = {
                "type": "action",
                "function_call": mapped_calls[0],
            }
        else:
            react_action = {
                "type": "action_batch",
                "function_calls": mapped_calls,
            }
        return json.dumps(react_action, ensure_ascii=False)