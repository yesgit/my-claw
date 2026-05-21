"""企业微信自动化工具（MyClaw 工具规范）。

通过截图 + 视觉模型读取消息，通过键盘模拟发送消息。
支持 Windows 和 macOS 平台。
"""
from __future__ import annotations

import logging
import os
import platform
import tempfile
from typing import Any

from backend.models import OperationRequest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 平台检测
# ---------------------------------------------------------------------------
_IS_MACOS = platform.system() == "Darwin"


class WeComTool:
    """企业微信自动化工具。

    Actions:
        read_messages  (medium) - 读取指定聊天的最新消息
        send_message   (high)   - 向指定聊天发送消息
        list_recent_chats (low) - 截图左侧消息列表，OCR 识别
        screenshot_chat (low)   - 截取聊天窗口截图
    """

    tool_name = "wecom"
    description = "企业微信自动化工具，支持读取消息、发送消息、截图等操作"

    supported_actions = {
        "read_messages": "medium",
        "send_message": "high",
        "list_recent_chats": "low",
        "screenshot_chat": "low",
    }

    def __init__(
        self,
        vision_api_url: str = "",
        vision_api_key: str = "",
        vision_model: str = "",
    ) -> None:
        """初始化企微工具。

        Args:
            vision_api_url: 视觉模型 API 地址（可选，默认 dashscope）。
            vision_api_key: 视觉模型 API Key。
            vision_model: 视觉模型名称（可选，默认 qwen3.6-plus）。
        """
        self._vision_api_url = vision_api_url
        self._vision_api_key = vision_api_key
        self._vision_model = vision_model
        self._reader: Any = None  # WeComReader 单例，延迟创建

    def _get_reader(self) -> Any:
        """获取或创建平台对应的 Reader 单例。"""
        if self._reader is None:
            try:
                if _IS_MACOS:
                    from backend.tools.wecom.macos.reader import MacWeComReader
                    self._reader = MacWeComReader()
                else:
                    from backend.tools.wecom.reader import WeComReader
                    self._reader = WeComReader()
            except ImportError as exc:
                missing = str(exc)
                hint = "请安装依赖后重试"
                if "pyobjc" in missing or "Quartz" in missing:
                    hint = "pip install pyobjc-framework-Quartz pyobjc-framework-Cocoa"
                elif "pyautogui" in missing:
                    hint = "pip install pyautogui"
                elif "Pillow" in missing or "PIL" in missing:
                    hint = "pip install Pillow"
                elif "pywinauto" in missing or "win32gui" in missing:
                    hint = "wecom 工具在 macOS 上需要使用 macOS 版本实现，请检查平台检测是否正确"
                raise ImportError(f"wecom 工具依赖缺失: {missing}。{hint}") from exc
            except RuntimeError as exc:
                raise RuntimeError(f"wecom 工具初始化失败: {exc}") from exc
        return self._reader

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
                "chat_name": {"type": "string", "description": "群聊或联系人名称"},
                "content": {"type": "string", "description": "要发送的消息内容（send_message 时必填）"},
            },
            "tool_name": self.tool_name,
            "description": self.description,
            "supported_actions": dict(self.supported_actions),
        }

    def execute(self, operation: OperationRequest) -> dict:
        """执行操作。"""
        if operation.action not in self.supported_actions:
            raise ValueError(f"wecom 不支持的 action: {operation.action}")

        try:
            if operation.action == "read_messages":
                return self._read_messages(operation)
            if operation.action == "send_message":
                return self._send_message(operation)
            if operation.action == "list_recent_chats":
                return self._list_recent_chats(operation)
            if operation.action == "screenshot_chat":
                return self._screenshot_chat(operation)

            raise ValueError(f"未实现的 action: {operation.action}")
        except (ImportError, RuntimeError) as exc:
            return {
                "ok": False,
                "error": str(exc),
                "hint": "请确认：1) 企业微信已打开并登录；2) 依赖已安装：pip install pyautogui pyobjc-framework-Quartz pyobjc-framework-Cocoa Pillow；3) 系统偏好设置 → 隐私 → 辅助功能/屏幕录制 权限已授予。",
            }

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _read_messages(self, operation: OperationRequest) -> dict:
        """读取指定聊天的最新消息。

        流程：连接 → 搜索聊天 → 滚到底部 → 截图 → 视觉模型识别 → 返回结构化消息
        """
        chat_name = operation.params.get("chat_name") or operation.resource
        if not chat_name:
            return {"ok": False, "error": "缺少 chat_name 参数"}

        reader = self._get_reader()

        # 连接
        if not reader.hwnd and not reader.connect():
            return {
                "ok": False,
                "error": "无法连接企业微信窗口",
                "hint": "请确认企业微信应用已打开且已登录，然后重试。如果已打开，请检查系统偏好设置 → 隐私 → 辅助功能/屏幕录制 权限是否已授予。",
            }
        try:
            # 搜索并打开聊天
            reader.search_and_open_chat(chat_name)

            # 滚动到最新消息
            reader.scroll_to_latest()
        except RuntimeError as exc:
            return {
                "ok": False,
                "error": f"操作企微窗口失败: {exc}",
                "hint": "请确认 pyautogui 已安装 (pip install pyautogui) 且辅助功能权限已授予。",
            }

        # 截图
        save_path = os.path.join(tempfile.gettempdir(), f"wecom_read_{int(id(operation))}.png")
        screenshot_path = reader.screenshot_window(save_path=save_path)

        # 视觉模型识别
        from backend.tools.wecom.vision import (
            READ_MESSAGES_PROMPT,
            call_vision_api,
            parse_messages_from_vision,
        )

        raw_text = call_vision_api(
            image_path=screenshot_path,
            prompt=READ_MESSAGES_PROMPT,
            api_url=self._vision_api_url or "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            api_key=self._vision_api_key,
            model=self._vision_model or "qwen3.6-plus",
        )

        if raw_text is None:
            return {"ok": False, "error": "视觉模型调用失败", "screenshot": screenshot_path}

        messages = parse_messages_from_vision(raw_text)

        return {
            "ok": True,
            "tool": self.tool_name,
            "action": "read_messages",
            "chat_name": chat_name,
            "messages": messages,
            "count": len(messages),
            "screenshot": screenshot_path,
        }

    def _send_message(self, operation: OperationRequest) -> dict:
        """向指定聊天发送消息。

        流程：连接 → 搜索聊天 → 点击输入框 → 粘贴 → 回车发送
        """
        chat_name = operation.params.get("chat_name") or operation.resource
        content = operation.params.get("content", "")

        if not chat_name:
            return {"ok": False, "error": "缺少 chat_name 参数"}
        if not content:
            return {"ok": False, "error": "缺少 content 参数"}

        reader = self._get_reader()

        # 连接
        if not reader.hwnd and not reader.connect():
            return {"ok": False, "error": "无法连接企业微信窗口"}

        # 搜索并打开聊天
        reader.search_and_open_chat(chat_name)

        # 发送消息
        success = reader.send_message(content)

        return {
            "ok": success,
            "tool": self.tool_name,
            "action": "send_message",
            "chat_name": chat_name,
            "content": content,
        }

    def _list_recent_chats(self, operation: OperationRequest) -> dict:
        """截图左侧消息列表，用视觉模型识别最近聊天。"""
        reader = self._get_reader()

        if not reader.hwnd and not reader.connect():
            return {"ok": False, "error": "无法连接企业微信窗口"}

        # 激活窗口（不需要搜索特定聊天，截全窗口即可看到左侧列表）
        reader.activate()

        # 截图
        save_path = os.path.join(tempfile.gettempdir(), f"wecom_list_{int(id(operation))}.png")
        screenshot_path = reader.screenshot_window(save_path=save_path)

        # 视觉模型识别
        from backend.tools.wecom.vision import (
            LIST_CHATS_PROMPT,
            call_vision_api,
            parse_chats_from_vision,
        )

        raw_text = call_vision_api(
            image_path=screenshot_path,
            prompt=LIST_CHATS_PROMPT,
            api_url=self._vision_api_url or "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            api_key=self._vision_api_key,
            model=self._vision_model or "qwen3.6-plus",
        )

        if raw_text is None:
            return {"ok": False, "error": "视觉模型调用失败", "screenshot": screenshot_path}

        chats = parse_chats_from_vision(raw_text)

        return {
            "ok": True,
            "tool": self.tool_name,
            "action": "list_recent_chats",
            "chats": chats,
            "count": len(chats),
            "screenshot": screenshot_path,
        }

    def _screenshot_chat(self, operation: OperationRequest) -> dict:
        """截取指定聊天窗口截图。"""
        chat_name = operation.params.get("chat_name") or operation.resource
        if not chat_name:
            return {"ok": False, "error": "缺少 chat_name 参数"}

        reader = self._get_reader()

        if not reader.hwnd and not reader.connect():
            return {"ok": False, "error": "无法连接企业微信窗口"}

        reader.search_and_open_chat(chat_name)
        reader.scroll_to_latest()

        save_path = os.path.join(tempfile.gettempdir(), f"wecom_screenshot_{int(id(operation))}.png")
        screenshot_path = reader.screenshot_window(save_path=save_path)

        return {
            "ok": True,
            "tool": self.tool_name,
            "action": "screenshot_chat",
            "chat_name": chat_name,
            "screenshot": screenshot_path,
        }