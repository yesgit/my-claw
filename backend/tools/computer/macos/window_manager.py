"""macOS 窗口管理器。

使用 pyobjc 的 Quartz 框架实现窗口查找、置前、截图。
"""
from __future__ import annotations

import base64
import logging
import os
import platform
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# macOS-only 依赖，条件导入
# ---------------------------------------------------------------------------
_IS_MACOS = platform.system() == "Darwin"

# 模块级变量，初始化为 None
_Quartz: Any = None
_kCGWindowListOptionOnScreenOnly: Any = None
_kCGNullWindowID: Any = None
_kCGWindowImageDefault: Any = None
_kCGWindowListExcludeDesktopElements: Any = None
_CGWindowListCopyWindowInfo: Any = None
_CGWindowListCreateImage: Any = None
_CGRectNull: Any = None
_NSWorkspace: Any = None
_NSRunningApplication: Any = None
_NSApplicationActivateIgnoringOtherApps: Any = None
_Image: Any = None


def _init_quartz() -> bool:
    """初始化 Quartz 框架，返回是否成功。"""
    global _Quartz, _kCGWindowListOptionOnScreenOnly, _kCGNullWindowID
    global _kCGWindowImageDefault, _kCGWindowListExcludeDesktopElements
    global _CGWindowListCopyWindowInfo, _CGWindowListCreateImage, _CGRectNull

    try:
        import Quartz as _Q  # type: ignore[import-untyped]
        _Quartz = _Q
        _kCGWindowListOptionOnScreenOnly = _Q.kCGWindowListOptionOnScreenOnly
        _kCGNullWindowID = _Q.kCGNullWindowID
        _kCGWindowImageDefault = _Q.kCGWindowImageDefault
        _kCGWindowListExcludeDesktopElements = _Q.kCGWindowListExcludeDesktopElements
        _CGWindowListCopyWindowInfo = _Q.CGWindowListCopyWindowInfo
        _CGWindowListCreateImage = _Q.CGWindowListCreateImage
        _CGRectNull = _Q.CGRectNull
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("pyobjc-framework-Quartz 导入失败: %s", exc)
        return False


def _init_appkit() -> bool:
    """初始化 AppKit 框架，返回是否成功。"""
    global _NSWorkspace, _NSRunningApplication, _NSApplicationActivateIgnoringOtherApps

    try:
        from AppKit import NSWorkspace as _NSW  # type: ignore[import-untyped]
        from AppKit import NSRunningApplication as _NSRA  # type: ignore[import-untyped]
        from AppKit import NSApplicationActivateIgnoringOtherApps as _NSAA  # type: ignore[import-untyped]

        _NSWorkspace = _NSW
        _NSRunningApplication = _NSRA
        _NSApplicationActivateIgnoringOtherApps = _NSAA
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("pyobjc-framework-Cocoa 导入失败: %s", exc)
        return False


def _init_pillow() -> bool:
    """初始化 Pillow，返回是否成功。"""
    global _Image

    try:
        from PIL import Image as _Image_mod  # type: ignore[import-untyped]
        _Image = _Image_mod
        return True
    except ImportError:
        logger.warning("Pillow 未安装，macOS 截图功能不可用")
        return False


# 模块加载时初始化
if _IS_MACOS:
    _init_quartz()
    _init_appkit()
    _init_pillow()


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MacWindowInfo:
    """macOS 窗口基本信息。"""

    window_id: int  # CGWindowID
    owner_name: str  # 进程名（如 "WeChat"）
    title: str  # 窗口标题
    bounds: tuple[float, float, float, float]  # (x, y, width, height)
    layer: int
    pid: int
    is_on_screen: bool

    def to_dict(self) -> dict[str, Any]:
        x, y, w, h = self.bounds
        return {
            "window_id": self.window_id,
            "owner_name": self.owner_name,
            "title": self.title,
            "bounds": {"x": x, "y": y, "width": w, "height": h},
            "layer": self.layer,
            "pid": self.pid,
            "is_on_screen": self.is_on_screen,
        }


# ---------------------------------------------------------------------------
# macOS 窗口管理器
# ---------------------------------------------------------------------------


class MacWindowManager:
    """macOS 桌面窗口管理：查找、置前、截图。"""

    DEFAULT_ACTION_DELAY = 0.3

    def __init__(self, action_delay: float = 0.3) -> None:
        self._action_delay = action_delay

    @staticmethod
    def is_available() -> bool:
        """检查窗口管理功能是否可用（需要 macOS + pyobjc）。"""
        return _IS_MACOS and _Quartz is not None

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
    ) -> list[MacWindowInfo]:
        """查找匹配条件的窗口。

        Args:
            class_name: macOS 上对应 owner_name（进程名，如 "WeChat"）。
            title: 窗口标题（子串匹配）。

        Returns:
            匹配的窗口列表。
        """
        self._ensure_available()

        # 获取所有 on-screen 窗口
        window_list = _CGWindowListCopyWindowInfo(
            _kCGWindowListOptionOnScreenOnly | _kCGWindowListExcludeDesktopElements,
            _kCGNullWindowID,
        )

        if window_list is None or len(window_list) == 0:
            return []

        results: list[MacWindowInfo] = []

        for win_dict in window_list:
            try:
                owner = win_dict.get("kCGWindowOwnerName", "") or ""
                win_title = win_dict.get("kCGWindowName", "") or ""
                layer = win_dict.get("kCGWindowLayer", 0)
                pid = win_dict.get("kCGWindowOwnerPID", 0)
                wid = win_dict.get("kCGWindowNumber", 0)
                bounds_dict = win_dict.get("kCGWindowBounds", {})
            except Exception:  # noqa: BLE001
                continue

            # 过滤：只保留应用层窗口（layer == 0）
            if layer != 0:
                continue

            # 过滤 class_name（对应 owner_name）
            if class_name and class_name.lower() not in owner.lower():
                continue

            # 过滤 title
            if title and title.lower() not in win_title.lower():
                continue

            bounds = (
                bounds_dict.get("X", 0),
                bounds_dict.get("Y", 0),
                bounds_dict.get("Width", 0),
                bounds_dict.get("Height", 0),
            )

            results.append(
                MacWindowInfo(
                    window_id=wid,
                    owner_name=owner,
                    title=win_title,
                    bounds=bounds,
                    layer=layer,
                    pid=pid,
                    is_on_screen=True,
                )
            )

        return results

    def get_window_info(self, window_id: int) -> MacWindowInfo | None:
        """获取指定窗口 ID 的信息。"""
        self._ensure_available()

        window_list = _CGWindowListCopyWindowInfo(
            _kCGWindowListOptionOnScreenOnly | _kCGWindowListExcludeDesktopElements,
            _kCGNullWindowID,
        )

        if window_list is None or len(window_list) == 0:
            return None

        for win_dict in window_list:
            try:
                wid = win_dict.get("kCGWindowNumber", 0)
                if wid == window_id:
                    owner = win_dict.get("kCGWindowOwnerName", "") or ""
                    win_title = win_dict.get("kCGWindowName", "") or ""
                    layer = win_dict.get("kCGWindowLayer", 0)
                    pid = win_dict.get("kCGWindowOwnerPID", 0)
                    bounds_dict = win_dict.get("kCGWindowBounds", {})
                    bounds = (
                        bounds_dict.get("X", 0),
                        bounds_dict.get("Y", 0),
                        bounds_dict.get("Width", 0),
                        bounds_dict.get("Height", 0),
                    )
                    return MacWindowInfo(
                        window_id=wid,
                        owner_name=owner,
                        title=win_title,
                        bounds=bounds,
                        layer=layer,
                        pid=pid,
                        is_on_screen=True,
                    )
            except Exception:  # noqa: BLE001
                continue

        return None

    # ------------------------------------------------------------------
    # 窗口操作
    # ------------------------------------------------------------------

    def bring_to_front(self, window_id: int) -> bool:
        """将窗口置前。

        macOS 上通过 NSRunningApplication 激活进程。
        注意：无法精确激活某个窗口，只能激活整个应用。
        """
        self._ensure_available()

        info = self.get_window_info(window_id)
        if info is None:
            return False

        try:
            apps = _NSWorkspace.sharedWorkspace().runningApplications()
            for app in apps:
                if app.processIdentifier() == info.pid:
                    app.activateWithOptions_(_NSApplicationActivateIgnoringOtherApps)
                    time.sleep(self._action_delay)
                    return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("bring_to_front 失败: %s", exc)

        return False

    def minimize(self, window_id: int) -> bool:
        """最小化窗口。

        macOS 上通过 AppleScript 或 Accessibility API 实现。
        这里使用简单的 pyautogui 快捷键 Cmd+M（如果窗口在前台）。
        """
        self._ensure_available()
        try:
            import pyautogui  # type: ignore[import-untyped]

            pyautogui.hotkey("command", "m")
            time.sleep(self._action_delay)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("minimize 失败: %s", exc)
            return False

    def restore(self, window_id: int) -> bool:
        """恢复窗口（取消最小化）。

        通过激活应用来恢复。
        """
        return self.bring_to_front(window_id)

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
            hwnd: macOS 上对应 window_id。为 None 时截取全屏。
            region: 截取区域 (left, top, right, bottom)，相对于窗口。
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
        window_id: int,
        region: tuple[int, int, int, int] | None,
        format: str,
    ) -> str:
        """截取指定窗口（screencapture 优先，Quartz 兜底）。"""
        self._ensure_available()

        # 获取窗口 bounds
        info = self.get_window_info(window_id)
        if info is None:
            raise RuntimeError(f"找不到窗口 {window_id}")

        x, y, w, h = info.bounds
        if region:
            abs_left = x + region[0]
            abs_top = y + region[1]
            abs_right = x + region[2]
            abs_bottom = y + region[3]
        else:
            abs_left, abs_top = x, y
            abs_right = x + w
            abs_bottom = y + h

        capture_width = abs_right - abs_left
        capture_height = abs_bottom - abs_top

        if capture_width <= 0 or capture_height <= 0:
            raise ValueError(
                f"截图区域无效: ({abs_left}, {abs_top}, {abs_right}, {abs_bottom})"
            )

        # --- 方式 1: screencapture -l <windowid> ---
        tmp_path = os.path.join(tempfile.gettempdir(), f"computer_screenshot_{window_id}.png")
        if not region:
            try:
                result = subprocess.run(
                    ["screencapture", "-l", str(window_id), "-o", "-x", tmp_path],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and os.path.isfile(tmp_path) and os.path.getsize(tmp_path) > 0:
                    with open(tmp_path, "rb") as f:
                        img_data = f.read()
                    os.unlink(tmp_path)
                    return base64.b64encode(img_data).decode("utf-8")
            except Exception:  # noqa: BLE001
                pass

        # --- 方式 2: screencapture -R x,y,w,h ---
        try:
            result = subprocess.run(
                ["screencapture", "-R",
                 f"{int(abs_left)},{int(abs_top)},{int(capture_width)},{int(capture_height)}",
                 "-x", tmp_path],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and os.path.isfile(tmp_path) and os.path.getsize(tmp_path) > 0:
                with open(tmp_path, "rb") as f:
                    img_data = f.read()
                os.unlink(tmp_path)
                return base64.b64encode(img_data).decode("utf-8")
        except Exception:  # noqa: BLE001
            pass

        # --- 方式 3: Quartz CGWindowListCreateImage（兜底）---
        capture_rect = _Quartz.CGRectMake(abs_left, abs_top, capture_width, capture_height)
        image_ref = _CGWindowListCreateImage(
            capture_rect, _kCGWindowListOptionOnScreenOnly, window_id, _kCGWindowImageDefault,
        )

        if image_ref is None:
            raise RuntimeError("所有截图方式均失败，可能缺少屏幕录制权限")

        return self._cgimage_to_base64(image_ref, format)

    def _screenshot_fullscreen(self, format: str) -> str:
        """截取全屏（使用 Quartz CGWindowListCreateImage）。"""
        # 使用 CGRectNull 截取所有屏幕
        image_ref = _CGWindowListCreateImage(
            _CGRectNull,
            _kCGWindowListOptionOnScreenOnly,
            _kCGNullWindowID,
            _kCGWindowImageDefault,
        )

        if image_ref is None:
            raise RuntimeError("全屏截图失败")

        return self._cgimage_to_base64(image_ref, format)

    @staticmethod
    def _cgimage_to_base64(image_ref: Any, format: str) -> str:
        """将 CGImage 转为 base64 编码的图片字符串。"""
        from AppKit import NSBitmapImageRep  # type: ignore[import-untyped]

        rep = NSBitmapImageRep.alloc().initWithCGImage_(image_ref)
        if rep is None:
            raise RuntimeError("NSBitmapImageRep 创建失败")

        # 确定格式类型
        fmt_type = {
            "png": 3,    # NSBitmapImageFileTypePNG
            "jpeg": 2,   # NSBitmapImageFileTypeJPEG
            "jpg": 2,
            "tiff": 0,   # NSBitmapImageFileTypeTIFF
            "bmp": 1,    # NSBitmapImageFileTypeBMP
            "gif": 4,    # NSBitmapImageFileTypeGIF
        }.get(format.lower(), 3)

        data = rep.representationUsingType_property_(fmt_type, None)
        if data is None:
            raise RuntimeError("图片编码失败")

        return base64.b64encode(bytes(data)).decode("utf-8")

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_available() -> None:
        """确保运行在 macOS 环境且依赖已安装。"""
        if not _IS_MACOS:
            raise RuntimeError("computer 工具的窗口管理仅支持 macOS")
        if _Quartz is None:
            raise RuntimeError(
                "pyobjc-framework-Quartz 未安装，请运行: pip install pyobjc-framework-Quartz"
            )
