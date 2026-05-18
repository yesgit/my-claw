from __future__ import annotations

import logging
import platform
from typing import Any

from backend.models import OperationRequest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 平台检测
# ---------------------------------------------------------------------------
_IS_WINDOWS = platform.system() == "Windows"
_IS_MACOS = platform.system() == "Darwin"


# ---------------------------------------------------------------------------
# ComputerTool — 跨平台桌面自动化工具
# ---------------------------------------------------------------------------


class ComputerTool:
    """桌面自动化工具（Computer Use）。

    跨平台实现：
    - Windows: pywin32 + uiautomation + Pillow
    - macOS: pyobjc (Quartz/AppKit) + pyautogui + Pillow

    自动根据当前操作系统选择对应的后端实现。
    """

    tool_name = "computer"
    description = "桌面自动化工具，支持窗口管理、控件读取、截图、键鼠模拟操作"
    supported_actions = {
        "find_window": "low",
        "take_screenshot": "low",
        "read_text": "low",
        "list_controls": "low",
        "read_list_items": "low",
        "click": "medium",
        "type_text": "medium",
        "send_keys": "medium",
        "scroll": "low",
        "wait": "low",
        "get_status": "low",
    }

    def __init__(
        self,
        action_delay: float = 0.3,
        typing_interval: float = 0.02,
    ) -> None:
        self._action_delay = action_delay
        self._typing_interval = typing_interval

        # 根据平台选择后端实现
        self._backend = self._create_backend()

    def _create_backend(self) -> Any:
        """根据当前平台创建对应的后端实现。"""
        if _IS_WINDOWS:
            return self._create_windows_backend()
        if _IS_MACOS:
            return self._create_macos_backend()
        return None

    def _create_windows_backend(self) -> Any:
        """创建 Windows 后端。"""
        from backend.tools.computer.window_manager import WindowManager
        from backend.tools.computer.reader import ControlReader
        from backend.tools.computer.actor import DesktopActor
        from backend.tools.computer.state import ComputerState

        return _WindowsBackend(
            window_mgr=WindowManager(action_delay=self._action_delay),
            reader=ControlReader(),
            actor=DesktopActor(
                action_delay=self._action_delay,
                typing_interval=self._typing_interval,
            ),
            state=ComputerState(),
        )

    def _create_macos_backend(self) -> Any:
        """创建 macOS 后端。"""
        from backend.tools.computer.macos.window_manager import MacWindowManager
        from backend.tools.computer.macos.reader import MacControlReader
        from backend.tools.computer.macos.actor import MacDesktopActor
        from backend.tools.computer.state import ComputerState

        return _MacBackend(
            window_mgr=MacWindowManager(action_delay=self._action_delay),
            reader=MacControlReader(),
            actor=MacDesktopActor(
                action_delay=self._action_delay,
                typing_interval=self._typing_interval,
            ),
            state=ComputerState(),
        )

    def describe(self) -> dict:
        """返回工具的标准自描述信息。"""
        actions = [
            {"name": action, "default_risk": risk}
            for action, risk in self.supported_actions.items()
        ]
        return {
            # 新版统一字段
            "tool": self.tool_name,
            "type": "local",
            "actions": actions,
            "input_schema": {
                "find_window": {
                    "type": "object",
                    "properties": {
                        "class_name": {
                            "type": "string",
                            "description": "窗口类名（Windows）或进程名（macOS，如 WeChat）",
                        },
                        "title": {"type": "string", "description": "窗口标题（子串匹配）"},
                    },
                },
                "take_screenshot": {
                    "type": "object",
                    "properties": {
                        "hwnd": {
                            "type": "integer",
                            "description": "窗口句柄（Windows）或窗口 ID（macOS），为空截取全屏",
                        },
                        "region": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "截取区域 [left, top, right, bottom]，相对于窗口",
                        },
                        "format": {"type": "string", "description": "图片格式，默认 png"},
                    },
                },
                "read_text": {
                    "type": "object",
                    "properties": {
                        "hwnd": {"type": "integer", "description": "窗口句柄（Windows）或窗口 ID（macOS）"},
                        "control_type": {
                            "type": "string",
                            "description": "控件类型过滤，如 ListControl（Windows）或 AXList（macOS）",
                        },
                        "name": {"type": "string", "description": "控件名称过滤（子串匹配）"},
                        "count": {"type": "integer", "description": "最多读取数量，默认 10"},
                        "depth": {"type": "integer", "description": "搜索深度，默认 6"},
                    },
                    "required": ["hwnd"],
                },
                "list_controls": {
                    "type": "object",
                    "properties": {
                        "hwnd": {"type": "integer", "description": "窗口句柄（Windows）或窗口 ID（macOS）"},
                        "control_type": {"type": "string", "description": "控件类型过滤"},
                        "name": {"type": "string", "description": "控件名称过滤（子串匹配）"},
                        "depth": {"type": "integer", "description": "遍历深度，默认 4"},
                        "max_count": {"type": "integer", "description": "最大返回数量，默认 50"},
                    },
                    "required": ["hwnd"],
                },
                "read_list_items": {
                    "type": "object",
                    "properties": {
                        "hwnd": {"type": "integer", "description": "窗口句柄（Windows）或窗口 ID（macOS）"},
                        "list_name": {"type": "string", "description": "列表控件名称（模糊匹配）"},
                        "count": {"type": "integer", "description": "最多读取数量，默认 20"},
                    },
                    "required": ["hwnd"],
                },
                "click": {
                    "type": "object",
                    "properties": {
                        "hwnd": {"type": "integer", "description": "窗口句柄（Windows）或窗口 ID（macOS）"},
                        "x": {"type": "integer", "description": "相对窗口 X 坐标"},
                        "y": {"type": "integer", "description": "相对窗口 Y 坐标"},
                        "control_type": {"type": "string", "description": "控件类型（UIA/AX 查找）"},
                        "name": {"type": "string", "description": "控件名称（UIA/AX 查找）"},
                        "button": {"type": "string", "description": "鼠标按钮：left/right，默认 left"},
                        "double": {"type": "boolean", "description": "是否双击，默认 false"},
                    },
                    "required": ["hwnd"],
                },
                "type_text": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "要输入的文本"},
                        "use_clipboard": {
                            "type": "boolean",
                            "description": "使用剪贴板粘贴（推荐），默认 true",
                        },
                        "hwnd": {"type": "integer", "description": "窗口句柄（确保窗口在前台）"},
                        "clear_first": {"type": "boolean", "description": "是否先清空，默认 false"},
                    },
                    "required": ["text"],
                },
                "send_keys": {
                    "type": "object",
                    "properties": {
                        "keys": {
                            "type": "string",
                            "description": "快捷键，如 {Ctrl}a, {Enter}（Windows 风格，macOS 自动映射）",
                        },
                    },
                    "required": ["keys"],
                },
                "scroll": {
                    "type": "object",
                    "properties": {
                        "hwnd": {"type": "integer", "description": "窗口句柄（Windows）或窗口 ID（macOS）"},
                        "direction": {"type": "string", "description": "方向：up/down/left/right，默认 down"},
                        "times": {"type": "integer", "description": "滚动次数，默认 3"},
                        "control_type": {"type": "string", "description": "滚动指定控件类型"},
                        "name": {"type": "string", "description": "滚动指定控件名称"},
                    },
                    "required": ["hwnd"],
                },
                "wait": {
                    "type": "object",
                    "properties": {
                        "seconds": {"type": "number", "description": "等待秒数（0.1-10.0）"},
                    },
                    "required": ["seconds"],
                },
                "get_status": {
                    "type": "object",
                    "properties": {},
                },
            },
            # 兼容旧字段
            "tool_name": self.tool_name,
            "description": self.description,
            "supported_actions": dict(self.supported_actions),
        }

    def execute(self, operation: OperationRequest) -> dict:
        """执行操作。"""
        action = operation.action
        params = operation.params or {}

        try:
            if self._backend is None:
                result = {
                    "ok": False,
                    "error": f"当前平台 ({platform.system()}) 不支持 computer 工具",
                    "hint": "computer 工具支持 Windows 和 macOS",
                }
                return result

            if action == "find_window":
                result = self._backend.find_window(params)
            elif action == "take_screenshot":
                result = self._backend.take_screenshot(params)
            elif action == "read_text":
                result = self._backend.read_text(params)
            elif action == "list_controls":
                result = self._backend.list_controls(params)
            elif action == "read_list_items":
                result = self._backend.read_list_items(params)
            elif action == "click":
                result = self._backend.click(params)
            elif action == "type_text":
                result = self._backend.type_text(params)
            elif action == "send_keys":
                result = self._backend.send_keys(params)
            elif action == "scroll":
                result = self._backend.scroll(params)
            elif action == "wait":
                result = self._backend.wait(params)
            elif action == "get_status":
                result = self._backend.get_status()
            else:
                raise ValueError(f"computer 工具不支持的动作: {action}")

            # 记录操作历史
            self._backend._state.record(action, params, result)

            return result

        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Windows 后端
# ---------------------------------------------------------------------------


class _WindowsBackend:
    """Windows 桌面自动化后端。"""

    def __init__(
        self,
        window_mgr: Any,
        reader: Any,
        actor: Any,
        state: Any,
    ) -> None:
        self._window_mgr = window_mgr
        self._reader = reader
        self._actor = actor
        self._state = state

    def find_window(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._window_mgr.is_available():
            return {
                "ok": False,
                "error": "窗口管理不可用（需要 Windows + pywin32）",
                "hint": "pip install pywin32",
            }

        class_name = params.get("class_name")
        title = params.get("title")

        windows = self._window_mgr.find_window(
            class_name=class_name if isinstance(class_name, str) else None,
            title=title if isinstance(title, str) else None,
        )

        if not windows:
            return {"ok": True, "windows": [], "count": 0, "message": "未找到匹配的窗口"}

        if windows:
            self._state.current_hwnd = windows[0].hwnd

        return {
            "ok": True,
            "windows": [w.to_dict() for w in windows],
            "count": len(windows),
        }

    def take_screenshot(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._window_mgr.screenshot_available():
            from backend.tools.computer.window_manager import get_pillow_diagnostic
            diag = get_pillow_diagnostic()
            error_parts = ["截图不可用"]
            if diag.get("pillow_error"):
                error_parts.append(f"原因: {diag['pillow_error']}")
            else:
                error_parts.append("原因: Pillow 未加载")
            error_parts.append(f"Python: {diag.get('python_executable', 'unknown')}")
            error_parts.append("提示: 请确保 Pillow 安装在 MyClaw 使用的 Python 环境中")
            return {"ok": False, "error": "。".join(error_parts), "diagnostic": diag}

        hwnd = params.get("hwnd")
        region = params.get("region")
        fmt = str(params.get("format", "png"))

        if hwnd is None:
            hwnd = self._state.current_hwnd

        parsed_region = None
        if isinstance(region, list) and len(region) == 4:
            parsed_region = tuple(int(v) for v in region)

        try:
            hwnd_int = int(hwnd) if hwnd is not None else None
        except (TypeError, ValueError):
            hwnd_int = None

        base64_image = self._window_mgr.take_screenshot(
            hwnd=hwnd_int,
            region=parsed_region,
            format=fmt,
        )

        return {
            "ok": True,
            "format": fmt,
            "image_base64": base64_image,
            "image_size": len(base64_image),
        }

    def read_text(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._reader.is_available():
            return {"ok": False, "error": "控件读取不可用（需要 Windows + uiautomation）", "hint": "pip install uiautomation"}

        hwnd = params.get("hwnd")
        if hwnd is None:
            return {"ok": False, "error": "缺少参数: hwnd"}

        try:
            hwnd_int = int(hwnd)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"hwnd 无效: {hwnd}"}

        control_type = params.get("control_type")
        name = params.get("name")
        count = int(params.get("count", 10))
        depth = int(params.get("depth", 6))

        texts = self._reader.read_text(
            hwnd=hwnd_int,
            control_type=str(control_type) if control_type else None,
            name=str(name) if name else None,
            count=count,
            depth=depth,
        )

        return {"ok": True, "count": len(texts), "items": texts}

    def list_controls(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._reader.is_available():
            return {"ok": False, "error": "控件读取不可用（需要 Windows + uiautomation）", "hint": "pip install uiautomation"}

        hwnd = params.get("hwnd")
        if hwnd is None:
            return {"ok": False, "error": "缺少参数: hwnd"}

        try:
            hwnd_int = int(hwnd)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"hwnd 无效: {hwnd}"}

        control_type = params.get("control_type")
        name = params.get("name")
        depth = int(params.get("depth", 4))
        max_count = int(params.get("max_count", 50))

        controls = self._reader.list_controls(
            hwnd=hwnd_int,
            control_type=str(control_type) if control_type else None,
            name=str(name) if name else None,
            depth=depth,
            max_count=max_count,
        )

        return {"ok": True, "count": len(controls), "controls": [c.to_dict() for c in controls]}

    def read_list_items(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._reader.is_available():
            return {"ok": False, "error": "控件读取不可用（需要 Windows + uiautomation）"}

        hwnd = params.get("hwnd")
        if hwnd is None:
            return {"ok": False, "error": "缺少参数: hwnd"}

        try:
            hwnd_int = int(hwnd)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"hwnd 无效: {hwnd}"}

        list_name = params.get("list_name")
        count = int(params.get("count", 20))

        items = self._reader.read_list_items(
            hwnd=hwnd_int,
            list_name=str(list_name) if list_name else None,
            count=count,
        )

        return {"ok": True, "count": len(items), "items": items}

    def click(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._actor.is_available():
            return {"ok": False, "error": "键鼠操作不可用（需要 Windows + uiautomation）"}

        hwnd = params.get("hwnd")
        if hwnd is None:
            return {"ok": False, "error": "缺少参数: hwnd"}

        try:
            hwnd_int = int(hwnd)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"hwnd 无效: {hwnd}"}

        self._window_mgr.bring_to_front(hwnd_int)
        self._state.current_hwnd = hwnd_int

        x = params.get("x")
        y = params.get("y")
        control_type = params.get("control_type")
        name = params.get("name")
        button = str(params.get("button", "left"))
        double = bool(params.get("double", False))

        return self._actor.click(
            hwnd=hwnd_int,
            x=int(x) if x is not None else None,
            y=int(y) if y is not None else None,
            control_type=str(control_type) if control_type else None,
            name=str(name) if name else None,
            button=button,
            double=double,
        )

    def type_text(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._actor.is_available():
            return {"ok": False, "error": "键鼠操作不可用（需要 Windows + uiautomation）"}

        text = params.get("text")
        if not text or not isinstance(text, str):
            return {"ok": False, "error": "缺少参数: text"}

        use_clipboard = bool(params.get("use_clipboard", True))
        hwnd = params.get("hwnd")
        clear_first = bool(params.get("clear_first", False))

        try:
            hwnd_int = int(hwnd) if hwnd is not None else None
        except (TypeError, ValueError):
            hwnd_int = None

        if hwnd_int is None:
            hwnd_int = self._state.current_hwnd

        return self._actor.type_text(
            text=text,
            use_clipboard=use_clipboard,
            hwnd=hwnd_int,
            clear_first=clear_first,
        )

    def send_keys(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._actor.is_available():
            return {"ok": False, "error": "键鼠操作不可用（需要 Windows + uiautomation）"}

        keys = params.get("keys")
        if not keys or not isinstance(keys, str):
            return {"ok": False, "error": "缺少参数: keys"}

        return self._actor.send_keys(keys=keys)

    def scroll(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._actor.is_available():
            return {"ok": False, "error": "键鼠操作不可用（需要 Windows + uiautomation）"}

        hwnd = params.get("hwnd")
        if hwnd is None:
            return {"ok": False, "error": "缺少参数: hwnd"}

        try:
            hwnd_int = int(hwnd)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"hwnd 无效: {hwnd}"}

        direction = str(params.get("direction", "down"))
        times = int(params.get("times", 3))
        control_type = params.get("control_type")
        name = params.get("name")

        return self._actor.scroll(
            hwnd=hwnd_int,
            direction=direction,
            times=times,
            control_type=str(control_type) if control_type else None,
            name=str(name) if name else None,
        )

    def wait(self, params: dict[str, Any]) -> dict[str, Any]:
        seconds = params.get("seconds", 1.0)
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            seconds = 1.0
        return self._actor.wait(seconds)

    def get_status(self) -> dict[str, Any]:
        status = self._state.get_status()
        status["window_available"] = self._window_mgr.is_available()
        status["screenshot_available"] = self._window_mgr.screenshot_available()
        status["screenshot_method"] = self._window_mgr.screenshot_method()
        status["reader_available"] = self._reader.is_available()
        status["actor_available"] = self._actor.is_available()
        status["platform"] = "Windows"

        # Pillow 诊断信息
        from backend.tools.computer.window_manager import get_pillow_diagnostic
        status["diagnostic"] = get_pillow_diagnostic()

        status["ok"] = True
        return status


# ---------------------------------------------------------------------------
# macOS 后端
# ---------------------------------------------------------------------------


class _MacBackend:
    """macOS 桌面自动化后端。"""

    def __init__(
        self,
        window_mgr: Any,
        reader: Any,
        actor: Any,
        state: Any,
    ) -> None:
        self._window_mgr = window_mgr
        self._reader = reader
        self._actor = actor
        self._state = state

    def find_window(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._window_mgr.is_available():
            return {
                "ok": False,
                "error": "窗口管理不可用（需要 macOS + pyobjc）",
                "hint": "pip install pyobjc-framework-Quartz",
            }

        class_name = params.get("class_name")
        title = params.get("title")

        windows = self._window_mgr.find_window(
            class_name=class_name if isinstance(class_name, str) else None,
            title=title if isinstance(title, str) else None,
        )

        if not windows:
            return {"ok": True, "windows": [], "count": 0, "message": "未找到匹配的窗口"}

        if windows:
            self._state.current_hwnd = windows[0].window_id

        return {
            "ok": True,
            "windows": [w.to_dict() for w in windows],
            "count": len(windows),
        }

    def take_screenshot(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._window_mgr.screenshot_available():
            return {"ok": False, "error": "截图不可用（需要 Pillow）", "hint": "pip install Pillow"}

        hwnd = params.get("hwnd")
        region = params.get("region")
        fmt = str(params.get("format", "png"))

        if hwnd is None:
            hwnd = self._state.current_hwnd

        parsed_region = None
        if isinstance(region, list) and len(region) == 4:
            parsed_region = tuple(int(v) for v in region)

        try:
            hwnd_int = int(hwnd) if hwnd is not None else None
        except (TypeError, ValueError):
            hwnd_int = None

        base64_image = self._window_mgr.take_screenshot(
            hwnd=hwnd_int,
            region=parsed_region,
            format=fmt,
        )

        return {
            "ok": True,
            "format": fmt,
            "image_base64": base64_image,
            "image_size": len(base64_image),
        }

    def read_text(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._reader.is_available():
            return {
                "ok": False,
                "error": "控件读取不可用（需要 macOS + pyobjc-framework-ApplicationServices）",
                "hint": "pip install pyobjc-framework-ApplicationServices",
            }

        hwnd = params.get("hwnd")
        if hwnd is None:
            return {"ok": False, "error": "缺少参数: hwnd"}

        try:
            hwnd_int = int(hwnd)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"hwnd 无效: {hwnd}"}

        control_type = params.get("control_type")
        name = params.get("name")
        count = int(params.get("count", 10))
        depth = int(params.get("depth", 6))

        texts = self._reader.read_text(
            hwnd=hwnd_int,
            control_type=str(control_type) if control_type else None,
            name=str(name) if name else None,
            count=count,
            depth=depth,
        )

        return {"ok": True, "count": len(texts), "items": texts}

    def list_controls(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._reader.is_available():
            return {
                "ok": False,
                "error": "控件读取不可用（需要 macOS + pyobjc-framework-ApplicationServices）",
                "hint": "pip install pyobjc-framework-ApplicationServices",
            }

        hwnd = params.get("hwnd")
        if hwnd is None:
            return {"ok": False, "error": "缺少参数: hwnd"}

        try:
            hwnd_int = int(hwnd)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"hwnd 无效: {hwnd}"}

        control_type = params.get("control_type")
        name = params.get("name")
        depth = int(params.get("depth", 4))
        max_count = int(params.get("max_count", 50))

        controls = self._reader.list_controls(
            hwnd=hwnd_int,
            control_type=str(control_type) if control_type else None,
            name=str(name) if name else None,
            depth=depth,
            max_count=max_count,
        )

        return {"ok": True, "count": len(controls), "controls": [c.to_dict() for c in controls]}

    def read_list_items(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._reader.is_available():
            return {"ok": False, "error": "控件读取不可用（需要 macOS + pyobjc）"}

        hwnd = params.get("hwnd")
        if hwnd is None:
            return {"ok": False, "error": "缺少参数: hwnd"}

        try:
            hwnd_int = int(hwnd)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"hwnd 无效: {hwnd}"}

        list_name = params.get("list_name")
        count = int(params.get("count", 20))

        items = self._reader.read_list_items(
            hwnd=hwnd_int,
            list_name=str(list_name) if list_name else None,
            count=count,
        )

        return {"ok": True, "count": len(items), "items": items}

    def click(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._actor.is_available():
            return {"ok": False, "error": "键鼠操作不可用（需要 macOS + pyautogui）", "hint": "pip install pyautogui"}

        hwnd = params.get("hwnd")
        if hwnd is None:
            return {"ok": False, "error": "缺少参数: hwnd"}

        try:
            hwnd_int = int(hwnd)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"hwnd 无效: {hwnd}"}

        self._window_mgr.bring_to_front(hwnd_int)
        self._state.current_hwnd = hwnd_int

        x = params.get("x")
        y = params.get("y")
        control_type = params.get("control_type")
        name = params.get("name")
        button = str(params.get("button", "left"))
        double = bool(params.get("double", False))

        return self._actor.click(
            hwnd=hwnd_int,
            x=int(x) if x is not None else None,
            y=int(y) if y is not None else None,
            control_type=str(control_type) if control_type else None,
            name=str(name) if name else None,
            button=button,
            double=double,
        )

    def type_text(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._actor.is_available():
            return {"ok": False, "error": "键鼠操作不可用（需要 macOS + pyautogui）", "hint": "pip install pyautogui"}

        text = params.get("text")
        if not text or not isinstance(text, str):
            return {"ok": False, "error": "缺少参数: text"}

        use_clipboard = bool(params.get("use_clipboard", True))
        hwnd = params.get("hwnd")
        clear_first = bool(params.get("clear_first", False))

        try:
            hwnd_int = int(hwnd) if hwnd is not None else None
        except (TypeError, ValueError):
            hwnd_int = None

        if hwnd_int is None:
            hwnd_int = self._state.current_hwnd

        return self._actor.type_text(
            text=text,
            use_clipboard=use_clipboard,
            hwnd=hwnd_int,
            clear_first=clear_first,
        )

    def send_keys(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._actor.is_available():
            return {"ok": False, "error": "键鼠操作不可用（需要 macOS + pyautogui）", "hint": "pip install pyautogui"}

        keys = params.get("keys")
        if not keys or not isinstance(keys, str):
            return {"ok": False, "error": "缺少参数: keys"}

        return self._actor.send_keys(keys=keys)

    def scroll(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._actor.is_available():
            return {"ok": False, "error": "键鼠操作不可用（需要 macOS + pyautogui）", "hint": "pip install pyautogui"}

        hwnd = params.get("hwnd")
        if hwnd is None:
            return {"ok": False, "error": "缺少参数: hwnd"}

        try:
            hwnd_int = int(hwnd)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"hwnd 无效: {hwnd}"}

        direction = str(params.get("direction", "down"))
        times = int(params.get("times", 3))
        control_type = params.get("control_type")
        name = params.get("name")

        return self._actor.scroll(
            hwnd=hwnd_int,
            direction=direction,
            times=times,
            control_type=str(control_type) if control_type else None,
            name=str(name) if name else None,
        )

    def wait(self, params: dict[str, Any]) -> dict[str, Any]:
        seconds = params.get("seconds", 1.0)
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            seconds = 1.0
        return self._actor.wait(seconds)

    def get_status(self) -> dict[str, Any]:
        status = self._state.get_status()
        status["window_available"] = self._window_mgr.is_available()
        status["screenshot_available"] = self._window_mgr.screenshot_available()
        status["reader_available"] = self._reader.is_available()
        status["actor_available"] = self._actor.is_available()
        status["platform"] = "macOS"
        status["ok"] = True
        return status
