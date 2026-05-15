from __future__ import annotations

import logging
import platform
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Windows-only 依赖，条件导入
# ---------------------------------------------------------------------------
_IS_WINDOWS = platform.system() == "Windows"

_uia: Any = None
_win32gui: Any = None
_win32con: Any = None

if _IS_WINDOWS:
    try:
        import uiautomation as _uia_mod  # type: ignore[import-untyped]
        _uia = _uia_mod
    except ImportError:
        pass

    try:
        import win32gui as _win32gui_mod  # type: ignore[import-untyped]
        import win32con as _win32con_mod  # type: ignore[import-untyped]
        _win32gui = _win32gui_mod
        _win32con = _win32con_mod
    except ImportError:
        pass

try:
    import pyperclip as _pyperclip  # type: ignore[import-untyped]
except ImportError:
    _pyperclip = None
    if _IS_WINDOWS:
        logger.warning("pyperclip 未安装，剪贴板粘贴功能不可用。请运行 pip install pyperclip")


# ---------------------------------------------------------------------------
# 键鼠操作执行器
# ---------------------------------------------------------------------------

class DesktopActor:
    """模拟键盘和鼠标操作。"""

    DEFAULT_ACTION_DELAY = 0.3
    DEFAULT_TYPING_INTERVAL = 0.02  # 每个字符间隔

    def __init__(
        self,
        action_delay: float = 0.3,
        typing_interval: float = 0.02,
    ) -> None:
        self._action_delay = action_delay
        self._typing_interval = typing_interval

    @staticmethod
    def is_available() -> bool:
        """检查操作功能是否可用。"""
        return _IS_WINDOWS and _uia is not None

    # ------------------------------------------------------------------
    # 点击
    # ------------------------------------------------------------------

    def click(
        self,
        hwnd: int,
        x: int | None = None,
        y: int | None = None,
        control_type: str | None = None,
        name: str | None = None,
        button: str = "left",
        double: bool = False,
    ) -> dict[str, Any]:
        """点击指定坐标或控件。

        Args:
            hwnd: 窗口句柄。
            x: 相对窗口的 X 坐标。
            y: 相对窗口的 Y 坐标。
            control_type: 控件类型（UIA 查找）。
            name: 控件名称（UIA 查找）。
            button: 鼠标按钮，"left" / "right" / "middle"。
            double: 是否双击。

        Returns:
            操作结果。
        """
        self._ensure_available()

        # 如果指定了控件，通过 UIA 查找并点击
        if control_type or name:
            return self._click_control(hwnd, control_type, name, button, double)

        # 坐标点击
        if x is None or y is None:
            return {"ok": False, "error": "必须指定 (x, y) 坐标或 (control_type/name) 控件"}

        return self._click_coordinate(hwnd, x, y, button, double)

    def _click_control(
        self,
        hwnd: int,
        control_type: str | None,
        name: str | None,
        button: str,
        double: bool,
    ) -> dict[str, Any]:
        """通过 UIA 控件点击。"""
        ctrl = self._find_control(hwnd, control_type, name)
        if ctrl is None:
            return {
                "ok": False,
                "error": f"未找到匹配的控件: type={control_type}, name={name}",
            }

        try:
            rect = ctrl.BoundingRectangle
            ctrl_info = {
                "control_type": ctrl.ControlTypeName,
                "name": ctrl.Name or "",
                "rect": (rect.left, rect.top, rect.right, rect.bottom),
            }
        except Exception:  # noqa: BLE001
            ctrl_info = {}

        try:
            if button == "left" and not double:
                ctrl.Click()
            elif button == "left" and double:
                ctrl.DoubleClick()
            elif button == "right":
                ctrl.RightClick()
            else:
                return {"ok": False, "error": f"不支持的按钮类型: {button}"}

            time.sleep(self._action_delay)
            return {"ok": True, "method": "uia_control", "control": ctrl_info}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"点击控件失败: {exc}"}

    def _click_coordinate(
        self,
        hwnd: int,
        x: int,
        y: int,
        button: str,
        double: bool,
    ) -> dict[str, Any]:
        """通过坐标点击（相对于窗口左上角）。"""
        self._ensure_win32()

        # 转换为绝对坐标
        left, top, _, _ = _win32gui.GetWindowRect(hwnd)
        abs_x = left + x
        abs_y = top + y

        try:
            if button == "left":
                _uia.Click(abs_x, abs_y, ratioX=0, ratioY=0, simulateMove=True)
                if double:
                    _uia.Click(abs_x, abs_y, ratioX=0, ratioY=0, simulateMove=True)
            elif button == "right":
                _uia.RightClick(abs_x, abs_y, ratioX=0, ratioY=0, simulateMove=True)
            else:
                return {"ok": False, "error": f"不支持的按钮类型: {button}"}

            time.sleep(self._action_delay)
            return {
                "ok": True,
                "method": "coordinate",
                "abs_x": abs_x,
                "abs_y": abs_y,
                "relative_x": x,
                "relative_y": y,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"坐标点击失败: {exc}"}

    # ------------------------------------------------------------------
    # 文本输入
    # ------------------------------------------------------------------

    def type_text(
        self,
        text: str,
        use_clipboard: bool = True,
        hwnd: int | None = None,
        clear_first: bool = False,
    ) -> dict[str, Any]:
        """在当前焦点处输入文本。

        Args:
            text: 要输入的文本。
            use_clipboard: 是否使用剪贴板粘贴（推荐，避免输入法问题）。
            hwnd: 窗口句柄（用于确保窗口在前台）。
            clear_first: 是否先清空已有内容（Ctrl+A → Delete）。

        Returns:
            操作结果。
        """
        self._ensure_available()

        if not text:
            return {"ok": False, "error": "文本不能为空"}

        # 确保窗口在前台
        if hwnd is not None:
            self._bring_to_front_safe(hwnd)

        # 清空已有内容
        if clear_first:
            _uia.SendKeys("{Ctrl}a", interval=self._typing_interval)
            time.sleep(0.1)
            _uia.SendKeys("{Delete}", interval=self._typing_interval)
            time.sleep(0.1)

        try:
            if use_clipboard:
                return self._type_via_clipboard(text)
            return self._type_via_sendkeys(text)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"输入文本失败: {exc}"}

    def _type_via_clipboard(self, text: str) -> dict[str, Any]:
        """通过剪贴板粘贴输入。"""
        if _pyperclip is None:
            # fallback 到 SendKeys
            logger.info("pyperclip 不可用，回退到 SendKeys")
            return self._type_via_sendkeys(text)

        _pyperclip.copy(text)
        time.sleep(0.1)
        _uia.SendKeys("{Ctrl}v", interval=self._typing_interval)
        time.sleep(self._action_delay)

        return {"ok": True, "method": "clipboard", "text_length": len(text)}

    def _type_via_sendkeys(self, text: str) -> dict[str, Any]:
        """通过 SendKeys 逐字符输入。"""
        _uia.SendKeys(text, interval=self._typing_interval)
        time.sleep(self._action_delay)

        return {"ok": True, "method": "sendkeys", "text_length": len(text)}

    # ------------------------------------------------------------------
    # 快捷键
    # ------------------------------------------------------------------

    def send_keys(self, keys: str, interval: float | None = None) -> dict[str, Any]:
        """发送快捷键。

        Args:
            keys: 快捷键字符串，如 "{Ctrl}a", "{Enter}", "{Ctrl}{Shift}n" 等。
                  使用 uiautomation 的 SendKeys 语法。
            interval: 按键间隔，默认使用实例设置。

        Returns:
            操作结果。
        """
        self._ensure_available()

        if not keys:
            return {"ok": False, "error": "keys 不能为空"}

        try:
            _uia.SendKeys(keys, interval=interval or self._typing_interval)
            time.sleep(self._action_delay)
            return {"ok": True, "keys": keys}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"发送快捷键失败: {exc}"}

    # ------------------------------------------------------------------
    # 滚动
    # ------------------------------------------------------------------

    def scroll(
        self,
        hwnd: int,
        direction: str = "down",
        times: int = 3,
        control_type: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """滚动窗口或指定控件。

        Args:
            hwnd: 窗口句柄。
            direction: 滚动方向，"up" / "down" / "left" / "right"。
            times: 滚动次数（每次一个单位）。
            control_type: 控件类型（滚动指定控件）。
            name: 控件名称。

        Returns:
            操作结果。
        """
        self._ensure_available()

        direction = direction.lower()
        if direction not in ("up", "down", "left", "right"):
            return {"ok": False, "error": f"不支持的滚动方向: {direction}"}

        # 查找目标控件
        target = None
        if control_type or name:
            target = self._find_control(hwnd, control_type, name)
            if target is None:
                return {"ok": False, "error": f"未找到匹配的控件: type={control_type}, name={name}"}

        try:
            for _ in range(times):
                if target is not None:
                    self._scroll_control(target, direction)
                else:
                    self._scroll_keyboard(direction)
                time.sleep(0.15)

            return {
                "ok": True,
                "direction": direction,
                "times": times,
                "target": "control" if target else "keyboard",
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"滚动失败: {exc}"}

    @staticmethod
    def _scroll_control(ctrl: Any, direction: str) -> None:
        """滚动指定控件。"""
        try:
            pattern = ctrl.GetScrollPattern()
            if pattern:
                if direction == "up":
                    pattern.ScrollSmallDecrement(_uia.UIA.ScrollPattern_NoAmount, -1)
                elif direction == "down":
                    pattern.ScrollSmallIncrement(_uia.UIA.ScrollPattern_NoAmount, 1)
                # 其他方向类似
                return
        except Exception:  # noqa: BLE001
            pass

        # Fallback: 使用鼠标滚轮
        rect = ctrl.BoundingRectangle
        center_x = (rect.left + rect.right) // 2
        center_y = (rect.top + rect.bottom) // 2
        delta = -120 if direction == "up" else 120
        _uia.SetCursorPos(center_x, center_y)
        # 模拟鼠标滚轮不太方便，改用键盘
        key = "{PageUp}" if direction == "up" else "{PageDown}"
        _uia.SendKeys(key)

    @staticmethod
    def _scroll_keyboard(direction: str) -> None:
        """通过键盘滚动。"""
        key_map = {
            "up": "{PageUp}",
            "down": "{PageDown}",
            "left": "{Left}",
            "right": "{Right}",
        }
        _uia.SendKeys(key_map[direction])

    # ------------------------------------------------------------------
    # 等待
    # ------------------------------------------------------------------

    def wait(self, seconds: float) -> dict[str, Any]:
        """等待指定时间。

        Args:
            seconds: 等待秒数，最大 10 秒。

        Returns:
            操作结果。
        """
        seconds = min(max(0.1, seconds), 10.0)
        time.sleep(seconds)
        return {"ok": True, "waited_seconds": seconds}

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _find_control(
        hwnd: int,
        control_type: str | None,
        name: str | None,
    ) -> Any:
        """通过 UIA 查找控件。"""
        root = _uia.ControlFromHandle(hwnd)
        if root is None:
            return None

        # 构建 UIA 搜索参数
        # 将字符串控件类型映射到 UIA 查找方法
        type_method_map = {
            "ButtonControl": root.ButtonControl,
            "EditControl": root.EditControl,
            "TextControl": root.TextControl,
            "ListControl": root.ListControl,
            "ListItemControl": root.ListItemControl,
            "TreeControl": root.TreeControl,
            "TreeItemControl": root.TreeItemControl,
            "TabControl": root.TabControl,
            "TabItemControl": root.TabItemControl,
            "MenuControl": root.MenuControl,
            "MenuItemControl": root.MenuItemControl,
            "ComboBoxControl": root.ComboBoxControl,
            "CheckBoxControl": root.CheckBoxControl,
            "RadioButtonControl": root.RadioButtonControl,
            "PaneControl": root.PaneControl,
            "GroupControl": root.GroupControl,
            "ToolBarControl": root.ToolBarControl,
            "DocumentControl": root.DocumentControl,
            "HyperlinkControl": root.HyperlinkControl,
            "ImageControl": root.ImageControl,
            "StatusBarControl": root.StatusBarControl,
        }

        kwargs: dict[str, Any] = {}
        if name:
            kwargs["Name"] = name
        kwargs["searchDepth"] = 8  # 搜索足够深

        if control_type and control_type in type_method_map:
            method = type_method_map[control_type]
            ctrl = method(**kwargs)
            if ctrl and ctrl.Exists(maxSearchSeconds=2):
                return ctrl

        # 不指定类型时，尝试按 Name 搜索
        if name:
            ctrl = root.Control(Name=name, searchDepth=8)
            if ctrl and ctrl.Exists(maxSearchSeconds=2):
                return ctrl

        return None

    @staticmethod
    def _bring_to_front_safe(hwnd: int) -> None:
        """安全地将窗口置前。"""
        try:
            if _win32gui and _win32con:
                _win32gui.ShowWindow(hwnd, _win32con.SW_RESTORE)
                _win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.2)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _ensure_available() -> None:
        """确保操作功能可用。"""
        if not _IS_WINDOWS:
            raise RuntimeError("computer 工具的键鼠操作仅支持 Windows")
        if _uia is None:
            raise RuntimeError("uiautomation 未安装，请运行 pip install uiautomation")

    @staticmethod
    def _ensure_win32() -> None:
        """确保 win32 可用。"""
        if _win32gui is None:
            raise RuntimeError("pywin32 未安装，请运行 pip install pywin32")