from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib import error, request


class LLMClientError(RuntimeError):
    pass


@dataclass(slots=True)
class OpenAICompatibleConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float = 60.0
    json_mode: bool = True


@dataclass(slots=True)
class OpenAICompatibleChatClient:
    config: OpenAICompatibleConfig
    opener: Callable[..., Any] = request.urlopen

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.0) -> str:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
        }
        if self.config.json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        req = request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
        )

        try:
            with self.opener(req, timeout=self.config.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMClientError(f"LLM HTTP error {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise LLMClientError(f"LLM 网络错误: {exc.reason}") from exc

        return self._extract_text(payload)

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