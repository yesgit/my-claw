from __future__ import annotations

import base64
import io
import logging
import platform
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Windows-only 依赖，做条件导入
# ---------------------------------------------------------------------------
_IS_WINDOWS = platform.system() == "Windows"

_win32gui: Any = None
_win32con: Any = None
_win32ui: Any = None
_ctypes: Any = None
_Image: Any = None

if _IS_WINDOWS:
    try:
        import win32gui as _win32gui_mod  # type: ignore[import-untyped]
        import win32con as _win32con_mod  # type: ignore[import-untyped]
        import win32ui as _win32ui_mod  # type: ignore[import-untyped]
        import ctypes as _ctypes_mod

        _win32gui = _win32gui_mod
        _win32con = _win32con_mod
        _win32ui = _win32ui_mod
        _ctypes = _ctypes_mod
    except ImportError:
        logger.warning("pywin32 未安装，computer 工具窗口管理功能不可用")

    try:
        from PIL import Image as _Image_mod

        _Image = _Image_mod
    except ImportError:
        logger.warning("Pillow 未安装，computer 工具截图功能不可用")


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class WindowInfo:
    """窗口基本信息。"""
    hwnd: int
    class_name: str
    title: str
    rect: tuple[int, int, int, int]  # (left, top, right, bottom)
    is_visible: bool
    is_minimized: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "class_name": self.class_name,
            "title": self.title,
            "rect": {"left": self.rect[0], "top": self.rect[1], "right": self.rect[2], "bottom": self.rect[3]},
            "width": self.rect[2] - self.rect[0],
            "height": self.rect[3] - self.rect[1],
            "is_visible": self.is_visible,
            "is_minimized": self.is_minimized,
        }


# ---------------------------------------------------------------------------
# 窗口管理器
# ---------------------------------------------------------------------------

class WindowManager:
    """Windows 桌面窗口管理：查找、置前、截图。"""

    # 默认操作延迟（秒）
    DEFAULT_ACTION_DELAY = 0.3

    def __init__(self, action_delay: float = 0.3) -> None:
        self._action_delay = action_delay

    @staticmethod
    def is_available() -> bool:
        """检查窗口管理功能是否可用（需要 Windows + pywin32）。"""
        return _IS_WINDOWS and _win32gui is not None

    @staticmethod
    def screenshot_available() -> bool:
        """检查截图功能是否可用（需要 Pillow）。"""
        return _Image is not None

    # ------------------------------------------------------------------
    # 查找窗口
    # ------------------------------------------------------------------

    def find_window(
        self,
        class_name: str | None = None,
        title: str | None = None,
    ) -> list[WindowInfo]:
        """查找匹配条件的窗口。

        Args:
            class_name: 窗口类名（精确匹配）。
            title: 窗口标题（子串匹配）。

        Returns:
            匹配的窗口列表。
        """
        self._ensure_windows()

        results: list[WindowInfo] = []

        def _enum_callback(hwnd: int, _: Any) -> None:
            wnd_class = _win32gui.GetClassName(hwnd)
            wnd_title = _win32gui.GetWindowText(hwnd)

            if class_name and wnd_class != class_name:
                return
            if title and title not in wnd_title:
                return

            rect = _win32gui.GetWindowRect(hwnd)
            is_visible = bool(_win32gui.IsWindowVisible(hwnd))
            # 检查是否最小化
            is_minimized = False
            try:
                placement = _win32gui.GetWindowPlacement(hwnd)
                # placement[1] 是 showCmd: SW_SHOWMINIMIZED = 2
                is_minimized = placement[1] == 2
            except Exception:  # noqa: BLE001
                pass

            results.append(WindowInfo(
                hwnd=hwnd,
                class_name=wnd_class,
                title=wnd_title,
                rect=rect,
                is_visible=is_visible,
                is_minimized=is_minimized,
            ))

        _win32gui.EnumWindows(_enum_callback, None)
        return results

    def get_window_info(self, hwnd: int) -> WindowInfo | None:
        """获取指定窗口句柄的信息。"""
        self._ensure_windows()

        if not _win32gui.IsWindow(hwnd):
            return None

        wnd_class = _win32gui.GetClassName(hwnd)
        wnd_title = _win32gui.GetWindowText(hwnd)
        rect = _win32gui.GetWindowRect(hwnd)
        is_visible = bool(_win32gui.IsWindowVisible(hwnd))
        is_minimized = False
        try:
            placement = _win32gui.GetWindowPlacement(hwnd)
            is_minimized = placement[1] == 2
        except Exception:  # noqa: BLE001
            pass

        return WindowInfo(
            hwnd=hwnd,
            class_name=wnd_class,
            title=wnd_title,
            rect=rect,
            is_visible=is_visible,
            is_minimized=is_minimized,
        )

    # ------------------------------------------------------------------
    # 窗口操作
    # ------------------------------------------------------------------

    def bring_to_front(self, hwnd: int) -> bool:
        """将窗口置前并恢复（如果最小化）。"""
        self._ensure_windows()

        if not _win32gui.IsWindow(hwnd):
            return False

        try:
            # 如果最小化则恢复
            _win32gui.ShowWindow(hwnd, _win32con.SW_RESTORE)
            time.sleep(self._action_delay)
            _win32gui.SetForegroundWindow(hwnd)
            time.sleep(self._action_delay)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("bring_to_front 失败: %s", exc)
            return False

    def minimize(self, hwnd: int) -> bool:
        """最小化窗口。"""
        self._ensure_windows()
        try:
            _win32gui.ShowWindow(hwnd, _win32con.SW_MINIMIZE)
            return True
        except Exception:  # noqa: BLE001
            return False

    def restore(self, hwnd: int) -> bool:
        """恢复窗口。"""
        self._ensure_windows()
        try:
            _win32gui.ShowWindow(hwnd, _win32con.SW_RESTORE)
            return True
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # 截图
    # ------------------------------------------------------------------

    def take_screenshot(
        self,
        hwnd: int | None = None,
        region: tuple[int, int, int, int] | None = None,
        format: str = "png",
    ) -> str:
        """截取窗口或全屏截图，返回 base64 编码的图片。

        Args:
            hwnd: 窗口句柄。为 None 时截取全屏。
            region: 截取区域 (left, top, right, bottom)，相对于窗口。
                    仅当 hwnd 不为 None 时有效。
            format: 图片格式，默认 png。

        Returns:
            base64 编码的图片字符串。
        """
        if not self.screenshot_available():
            raise RuntimeError("截图功能不可用：需要安装 Pillow")

        if hwnd is not None:
            return self._screenshot_window(hwnd, region, format)
        return self._screenshot_fullscreen(format)

    def _screenshot_window(
        self,
        hwnd: int,
        region: tuple[int, int, int, int] | None,
        format: str,
    ) -> str:
        """截取指定窗口。"""
        self._ensure_windows()

        # 获取窗口 DC
        left, top, right, bottom = _win32gui.GetWindowRect(hwnd)
        width = right - left
        height = bottom - top

        if region:
            # region 相对于窗口左上角
            abs_left = left + region[0]
            abs_top = top + region[1]
            abs_right = left + region[2]
            abs_bottom = top + region[3]
        else:
            abs_left, abs_top = left, top
            abs_right, abs_bottom = right, bottom

        capture_width = abs_right - abs_left
        capture_height = abs_bottom - abs_top

        if capture_width <= 0 or capture_height <= 0:
            raise ValueError(f"截图区域无效: ({abs_left}, {abs_top}, {abs_right}, {abs_bottom})")

        # 使用 Pillow 截图
        img = _Image.grab(bbox=(abs_left, abs_top, abs_right, abs_bottom))

        buf = io.BytesIO()
        img.save(buf, format=format.upper())
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def _screenshot_fullscreen(self, format: str) -> str:
        """截取全屏。"""
        img = _Image.grab()
        buf = io.BytesIO()
        img.save(buf, format=format.upper())
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_windows() -> None:
        """确保运行在 Windows 环境且依赖已安装。"""
        if not _IS_WINDOWS:
            raise RuntimeError("computer 工具的窗口管理仅支持 Windows")
        if _win32gui is None:
            raise RuntimeError("pywin32 未安装，请运行 pip install pywin32")