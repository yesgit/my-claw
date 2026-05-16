"""macOS 键鼠操作执行器。

使用 pyautogui 实现跨平台的键鼠模拟操作。
macOS 上需要授予辅助功能权限。
"""
from __future__ import annotations

import logging
import platform
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# macOS-only 依赖，条件导入
# ---------------------------------------------------------------------------
_IS_MACOS = platform.system() == "Darwin"

_pyautogui: Any = None
_pyperclip: Any = None

if _IS_MACOS:
    try:
        import pyautogui as _pag  # type: ignore[import-untyped]

        _pyautogui = _pag
        # 安全设置：启用故障保护（鼠标移到左上角可中断）
        _pyautogui.FAILSAFE = True
    except ImportError:
        logger.warning("pyautogui 未安装，macOS 键鼠操作不可用")

    try:
        import pyperclip as _pc  # type: ignore[import-untyped]

        _pyperclip = _pc
    except ImportError:
        logger.warning("pyperclip 未安装，剪贴板粘贴功能不可用")


# ---------------------------------------------------------------------------
# macOS 键鼠操作执行器
# ---------------------------------------------------------------------------


class MacDesktopActor:
    """模拟键盘和鼠标操作（macOS 实现）。"""

    DEFAULT_ACTION_DELAY = 0.3
    DEFAULT_TYPING_INTERVAL = 0.02

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
        return _IS_MACOS and _pyautogui is not None

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
            hwnd: macOS 上对应 window_id（用于定位窗口）。
            x: 相对窗口的 X 坐标。
            y: 相对窗口的 Y 坐标。
            control_type: 控件角色（如 AXButton），通过 Accessibility 查找。
            name: 控件名称（AXTitle）。
            button: 鼠标按钮，"left" / "right"。
            double: 是否双击。

        Returns:
            操作结果。
        """
        self._ensure_available()

        # 如果指定了控件，通过 Accessibility 查找并点击
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
        """通过 Accessibility API 点击控件。"""
        ax_element = self._find_ax_control(hwnd, control_type, name)
        if ax_element is None:
            return {
                "ok": False,
                "error": f"未找到匹配的控件: type={control_type}, name={name}",
            }

        try:
            # 获取控件位置
            pos = self._get_ax_position(ax_element)
            if pos is None:
                return {"ok": False, "error": "无法获取控件位置"}

            center_x = int(pos[0] + pos[2] / 2)
            center_y = int(pos[1] + pos[3] / 2)

            # 使用 pyautogui 点击
            _pyautogui.moveTo(center_x, center_y, duration=0.1)
            time.sleep(0.05)

            btn = "left" if button == "left" else "right"
            if double:
                _pyautogui.doubleClick(button=btn)
            else:
                _pyautogui.click(button=btn)

            time.sleep(self._action_delay)

            return {
                "ok": True,
                "method": "accessibility",
                "control": {
                    "control_type": control_type or "",
                    "name": name or "",
                    "position": {"x": center_x, "y": center_y},
                },
            }
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
        # 获取窗口位置
        win_bounds = self._get_window_bounds(hwnd)
        if win_bounds is None:
            return {"ok": False, "error": f"无法获取窗口 {hwnd} 的位置"}

        abs_x = int(win_bounds[0] + x)
        abs_y = int(win_bounds[1] + y)

        try:
            _pyautogui.moveTo(abs_x, abs_y, duration=0.1)
            time.sleep(0.05)

            btn = "left" if button == "left" else "right"
            if double:
                _pyautogui.doubleClick(button=btn)
            else:
                _pyautogui.click(button=btn)

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
            hwnd: 窗口 ID（用于确保窗口在前台）。
            clear_first: 是否先清空已有内容（Cmd+A → Delete）。

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
            _pyautogui.hotkey("command", "a")
            time.sleep(0.1)
            _pyautogui.press("delete")
            time.sleep(0.1)

        try:
            if use_clipboard:
                return self._type_via_clipboard(text)
            return self._type_via_keyboard(text)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"输入文本失败: {exc}"}

    def _type_via_clipboard(self, text: str) -> dict[str, Any]:
        """通过剪贴板粘贴输入。"""
        if _pyperclip is None:
            logger.info("pyperclip 不可用，回退到键盘输入")
            return self._type_via_keyboard(text)

        _pyperclip.copy(text)
        time.sleep(0.1)
        _pyautogui.hotkey("command", "v")
        time.sleep(self._action_delay)

        return {"ok": True, "method": "clipboard", "text_length": len(text)}

    def _type_via_keyboard(self, text: str) -> dict[str, Any]:
        """通过键盘逐字符输入。"""
        _pyautogui.write(text, interval=self._typing_interval)
        time.sleep(self._action_delay)

        return {"ok": True, "method": "keyboard", "text_length": len(text)}

    # ------------------------------------------------------------------
    # 快捷键
    # ------------------------------------------------------------------

    def send_keys(self, keys: str, interval: float | None = None) -> dict[str, Any]:
        """发送快捷键。

        Args:
            keys: 快捷键字符串，格式如 "{Ctrl}a", "{Enter}"。
                   支持 pyautogui 的 hotkey 语法。
            interval: 按键间隔，默认使用实例设置。

        Returns:
            操作结果。
        """
        self._ensure_available()

        if not keys:
            return {"ok": False, "error": "keys 不能为空"}

        try:
            # 解析快捷键格式
            # 支持格式: "{Ctrl}a" → hotkey("ctrl", "a")
            #           "{Enter}" → press("enter")
            #           "{Ctrl}{Shift}n" → hotkey("ctrl", "shift", "n")
            self._parse_and_send_keys(keys)
            time.sleep(self._action_delay)
            return {"ok": True, "keys": keys}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"发送快捷键失败: {exc}"}

    def _parse_and_send_keys(self, keys: str) -> None:
        """解析并发送快捷键字符串。

        支持的格式：
        - 单键: "a", "Enter", "Escape"
        - 组合键: "{Ctrl}a", "{Cmd}{Shift}n"
        - 多个: "{Ctrl}a{Enter}"
        """
        import re

        # 解析 {Modifier}key 模式
        pattern = r"\{(\w+)\}"
        parts = re.split(pattern, keys)

        i = 0
        while i < len(parts):
            part = parts[i]
            if not part:
                i += 1
                continue

            # 检查是否是修饰键后的按键
            if i + 2 < len(parts) and re.match(r"^\w+$", parts[i + 1]):
                # 组合键: {Ctrl}a
                modifiers = [part.lower()]
                key = parts[i + 1].lower()
                self._send_hotkey(modifiers, key)
                i += 2
            elif re.match(r"^\w+$", part):
                # 单键
                self._send_single_key(part)
                i += 1
            else:
                i += 1

    def _send_hotkey(self, modifiers: list[str], key: str) -> None:
        """发送组合键。"""
        # 映射 Windows 修饰键到 macOS
        mod_map = {
            "ctrl": "command",  # macOS 上 Ctrl 通常对应 Cmd
            "control": "command",
            "cmd": "command",
            "alt": "option",
            "shift": "shift",
            "win": "command",
            "windows": "command",
        }

        mapped_mods = [mod_map.get(m, m) for m in modifiers]
        # 过滤掉重复的
        mapped_mods = list(dict.fromkeys(mapped_mods))

        _pyautogui.hotkey(*mapped_mods, key)

    def _send_single_key(self, key: str) -> None:
        """发送单键。"""
        key_map = {
            "Enter": "enter",
            "Return": "enter",
            "Tab": "tab",
            "Escape": "esc",
            "Esc": "esc",
            "Backspace": "backspace",
            "Delete": "delete",
            "Space": "space",
            "Up": "up",
            "Down": "down",
            "Left": "left",
            "Right": "right",
            "Home": "home",
            "End": "end",
            "PageUp": "pageup",
            "PageDown": "pagedown",
            "F1": "f1",
            "F2": "f2",
            "F3": "f3",
            "F4": "f4",
            "F5": "f5",
            "F6": "f6",
            "F7": "f7",
            "F8": "f8",
            "F9": "f9",
            "F10": "f10",
            "F11": "f11",
            "F12": "f12",
        }

        mapped = key_map.get(key, key.lower())
        _pyautogui.press(mapped)

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
            hwnd: 窗口 ID。
            direction: 滚动方向，"up" / "down" / "left" / "right"。
            times: 滚动次数。
            control_type: 控件角色（滚动指定控件）。
            name: 控件名称。

        Returns:
            操作结果。
        """
        self._ensure_available()

        direction = direction.lower()
        if direction not in ("up", "down", "left", "right"):
            return {"ok": False, "error": f"不支持的滚动方向: {direction}"}

        try:
            # 如果指定了控件，先点击控件确保焦点
            if control_type or name:
                click_result = self._click_control(hwnd, control_type, name, "left", False)
                if not click_result.get("ok"):
                    return click_result

            # 使用 pyautogui 滚动
            # macOS 上 scroll 的 clicks 参数：正数向上，负数向下
            if direction == "up":
                _pyautogui.scroll(times)
            elif direction == "down":
                _pyautogui.scroll(-times)
            elif direction == "left":
                _pyautogui.hscroll(-times)
            elif direction == "right":
                _pyautogui.hscroll(times)

            time.sleep(self._action_delay)

            return {
                "ok": True,
                "direction": direction,
                "times": times,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"滚动失败: {exc}"}

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
    def _get_window_bounds(window_id: int) -> tuple[float, float, float, float] | None:
        """获取窗口的 bounds (x, y, width, height)。"""
        try:
            import Quartz  # type: ignore[import-untyped]

            window_list = Quartz.CGWindowListCreate(
                Quartz.kCGWindowListOptionOnScreenOnly
                | Quartz.kCGWindowListExcludeDesktopElements,
                Quartz.kCGNullWindowID,
            )
            if window_list is None:
                return None

            count = window_list.getCount()
            for i in range(count):
                try:
                    win_dict = window_list.objectAtIndex(i)
                except Exception:  # noqa: BLE001
                    continue

                wid = win_dict.get("kCGWindowNumber", 0)
                if wid == window_id:
                    bounds = win_dict.get("kCGWindowBounds", {})
                    return (
                        bounds.get("X", 0),
                        bounds.get("Y", 0),
                        bounds.get("Width", 0),
                        bounds.get("Height", 0),
                    )
        except ImportError:
            pass

        return None

    @staticmethod
    def _find_ax_control(
        hwnd: int,
        control_type: str | None,
        name: str | None,
    ) -> Any | None:
        """通过 macOS Accessibility API 查找控件。"""
        try:
            import Quartz  # type: ignore[import-untyped]
            import ApplicationServices as _AX  # type: ignore[import-untyped]

            # 获取窗口 PID
            window_list = Quartz.CGWindowListCreate(
                Quartz.kCGWindowListOptionOnScreenOnly
                | Quartz.kCGWindowListExcludeDesktopElements,
                Quartz.kCGNullWindowID,
            )
            if window_list is None:
                return None

            pid = None
            count = window_list.getCount()
            for i in range(count):
                try:
                    win_dict = window_list.objectAtIndex(i)
                except Exception:  # noqa: BLE001
                    continue
                if win_dict.get("kCGWindowNumber", 0) == hwnd:
                    pid = win_dict.get("kCGWindowOwnerPID", 0)
                    break

            if pid is None:
                return None

            # 获取 AX 应用对象
            app_ref = _AX.AXUIElementCreateApplication(pid)
            if app_ref is None:
                return None

            # 搜索控件
            return _search_ax_element(app_ref, control_type, name, max_depth=8)

        except ImportError:
            return None

    @staticmethod
    def _get_ax_position(element: Any) -> tuple[float, float, float, float] | None:
        """获取 AX 元素的位置。"""
        try:
            import ApplicationServices as _AX  # type: ignore[import-untyped]

            pos = _AX.AXUIElementCopyAttributeValue(element, "AXPosition", None)
            size = _AX.AXUIElementCopyAttributeValue(element, "AXSize", None)
            if pos and pos[0] == 0 and pos[1] and size and size[0] == 0 and size[1]:
                return (pos[1][0], pos[1][1], size[1][0], size[1][1])
        except Exception:  # noqa: BLE001
            pass
        return None

    @staticmethod
    def _bring_to_front_safe(window_id: int) -> None:
        """安全地将窗口置前。"""
        try:
            from AppKit import NSWorkspace  # type: ignore[import-untyped]
            from AppKit import NSApplicationActivateIgnoringOtherApps  # type: ignore[import-untyped]

            import Quartz  # type: ignore[import-untyped]

            window_list = Quartz.CGWindowListCreate(
                Quartz.kCGWindowListOptionOnScreenOnly
                | Quartz.kCGWindowListExcludeDesktopElements,
                Quartz.kCGNullWindowID,
            )
            if window_list is None:
                return

            pid = None
            count = window_list.getCount()
            for i in range(count):
                try:
                    win_dict = window_list.objectAtIndex(i)
                except Exception:  # noqa: BLE001
                    continue
                if win_dict.get("kCGWindowNumber", 0) == window_id:
                    pid = win_dict.get("kCGWindowOwnerPID", 0)
                    break

            if pid is None:
                return

            apps = NSWorkspace.sharedWorkspace().runningApplications()
            for app in apps:
                if app.processIdentifier() == pid:
                    app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                    time.sleep(0.2)
                    return
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _ensure_available() -> None:
        """确保操作功能可用。"""
        if not _IS_MACOS:
            raise RuntimeError("computer 工具的键鼠操作仅支持 macOS")
        if _pyautogui is None:
            raise RuntimeError("pyautogui 未安装，请运行: pip install pyautogui")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _search_ax_element(
    element: Any,
    control_type: str | None,
    name: str | None,
    max_depth: int,
) -> Any | None:
    """递归搜索 AX 元素。"""
    if max_depth <= 0:
        return None

    try:
        import ApplicationServices as _AX  # type: ignore[import-untyped]

        role_result = _AX.AXUIElementCopyAttributeValue(element, "AXRole", None)
        title_result = _AX.AXUIElementCopyAttributeValue(element, "AXTitle", None)

        role = role_result[1] if role_result and role_result[0] == 0 else ""
        title = title_result[1] if title_result and title_result[0] == 0 else ""

        # 检查是否匹配
        role_match = not control_type or role == control_type
        name_match = not name or (name in (title or ""))

        if role_match and name_match:
            return element

        # 递归子元素
        children_result = _AX.AXUIElementCopyAttributeValue(element, "AXChildren", None)
        if children_result and children_result[0] == 0 and children_result[1]:
            for child in list(children_result[1]):
                result = _search_ax_element(child, control_type, name, max_depth - 1)
                if result is not None:
                    return result
    except Exception:  # noqa: BLE001
        pass

    return None
