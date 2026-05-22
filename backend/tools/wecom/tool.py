"""企业微信自动化工具（MyClaw 工具规范）。

通过截图 + 视觉模型读取消息，通过键盘模拟发送消息。
支持 Windows 和 macOS 平台。
"""
from __future__ import annotations

import logging
import os
import platform
import tempfile
import time
from typing import Any, Callable

from backend.models import OperationRequest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 平台检测
# ---------------------------------------------------------------------------
_IS_MACOS = platform.system() == "Darwin"


def _wecom_platform_hint() -> str:
    """根据当前平台返回 wecom 工具的依赖安装提示。"""
    if _IS_MACOS:
        return (
            "请确认：1) 企业微信已打开并登录；"
            "2) 依赖已安装：pip install pyautogui pyobjc-framework-Quartz pyobjc-framework-Cocoa Pillow；"
            "3) 系统偏好设置 → 隐私 → 辅助功能/屏幕录制 权限已授予。"
        )
    else:
        return (
            "请确认：1) 企业微信已打开并登录；"
            "2) 依赖已安装：pip install pyautogui Pillow pywin32 pywinauto；"
            "3) 如果仍然报错，请尝试以管理员身份运行。"
        )



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

    # GUI 自动化操作（需要键鼠模拟）前的倒计时秒数
    GUI_COUNTDOWN_SECONDS = 3

    # 不涉及 GUI 自动化的 action（仅需截图，不需要倒计时）
    _NO_GUI_ACTIONS = frozenset({"list_recent_chats"})

    def __init__(
        self,
        vision_api_url: str = "",
        vision_api_key: str = "",
        vision_model: str = "",
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """初始化企微工具。

        Args:
            vision_api_url: 视觉模型 API 地址（可选，默认 dashscope）。
            vision_api_key: 视觉模型 API Key。
            vision_model: 视觉模型名称（可选，默认 qwen3.6-plus）。
            event_callback: 事件回调（用于向前端发送倒计时等通知）。
        """
        self._vision_api_url = vision_api_url
        self._vision_api_key = vision_api_key
        self._vision_model = vision_model
        self._reader: Any = None  # WeComReader 单例，延迟创建
        self._event_callback = event_callback

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
                    hint = "pip install pywin32 pywinauto"
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

    def _emit_event(self, event: dict[str, Any]) -> None:
        """发送事件通知（倒计时等）。"""
        if self._event_callback is not None:
            self._event_callback(event)

    def _countdown_before_gui(self, action: str, detail: str = "") -> None:
        """GUI 自动化操作前倒计时，提醒用户暂停操作。

        通过 event_callback 逐秒发送倒计时事件，前端可据此显示提示。
        同时在日志中记录倒计时过程。

        Args:
            action: 即将执行的操作名称。
            detail: 补充描述（如目标聊天名）。
        """
        seconds = self.GUI_COUNTDOWN_SECONDS
        message = f"即将执行 {action}"
        if detail:
            message += f"（{detail}）"
        message += "，请暂停操作企业微信"

        logger.info("[WeCom 倒计时] %s，%d 秒后开始...", message, seconds)

        for remaining in range(seconds, 0, -1):
            self._emit_event({
                "type": "wecom_countdown",
                "tool": self.tool_name,
                "action": action,
                "message": message,
                "remaining_seconds": remaining,
            })
            time.sleep(1)

        self._emit_event({
            "type": "wecom_countdown_done",
            "tool": self.tool_name,
            "action": action,
            "message": f"倒计时结束，开始执行 {action}",
        })
        logger.info("[WeCom 倒计时] 开始执行 %s", action)

    def _notify_gui_done(self, action: str, result: dict) -> None:
        """GUI 自动化操作完成后发送通知。

        前端可据此显示"操作完成，可恢复操作"提示，并触发系统级通知。
        """
        ok = result.get("ok", False)
        status = "成功" if ok else "失败"
        message = f"企业微信 {action} 已完成（{status}），你可以继续操作企业微信了"

        self._emit_event({
            "type": "wecom_gui_done",
            "tool": self.tool_name,
            "action": action,
            "ok": ok,
            "message": message,
        })
        logger.info("[WeCom 通知] %s", message)

    def execute(self, operation: OperationRequest) -> dict:
        """执行操作。"""
        if operation.action not in self.supported_actions:
            raise ValueError(f"wecom 不支持的 action: {operation.action}")

        needs_gui = operation.action not in self._NO_GUI_ACTIONS

        # GUI 自动化操作前倒计时提醒（仅涉及键鼠模拟的 action）
        # 独立 try 保护：即使倒计时事件推送失败（如 SSE 断开），仍继续执行操作
        if needs_gui:
            try:
                chat_name = operation.params.get("chat_name") or operation.resource or ""
                self._countdown_before_gui(operation.action, detail=chat_name)
            except Exception:
                logger.exception("[WeCom] 倒计时事件推送失败，跳过倒计时继续执行")

        try:
            if operation.action == "read_messages":
                result = self._read_messages(operation)
            elif operation.action == "send_message":
                result = self._send_message(operation)
            elif operation.action == "list_recent_chats":
                result = self._list_recent_chats(operation)
            elif operation.action == "screenshot_chat":
                result = self._screenshot_chat(operation)
            else:
                raise ValueError(f"未实现的 action: {operation.action}")
        except Exception as exc:
            logger.exception("[WeCom] 执行 %s 失败", operation.action)
            result = {
                "ok": False,
                "error": str(exc),
                "hint": _wecom_platform_hint(),
            }

        # GUI 操作完成后发送恢复提示（即使回调异常也不影响结果返回）
        if needs_gui:
            try:
                self._notify_gui_done(operation.action, result)
            except Exception:
                logger.exception("[WeCom] 发送 gui_done 事件失败")

        return result

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

        # 防御性校验：chat_name 不应该是 action 名称（说明参数解析出了问题）
        if chat_name in self.supported_actions:
            return {
                "ok": False,
                "error": f"chat_name 参数值为 action 名称 '{chat_name}'，不是有效的群聊名称。"
                         f"请检查 params.chat_name 是否正确传入。",
            }

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
        if chat_name in self.supported_actions:
            return {
                "ok": False,
                "error": f"chat_name 参数值为 action 名称 '{chat_name}'，不是有效的群聊名称。",
            }
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
        if chat_name in self.supported_actions:
            return {
                "ok": False,
                "error": f"chat_name 参数值为 action 名称 '{chat_name}'，不是有效的群聊名称。",
            }

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