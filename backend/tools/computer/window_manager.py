from __future__ import annotations

import base64
import io
import logging
import platform
import struct
import sys
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
_pillow_error: str | None = None  # 记录 Pillow 加载失败的详细原因


def _init_pillow() -> bool:
    """延迟初始化 Pillow，每次调用都会尝试导入。已成功则跳过。

    使得 Pillow 即使在进程启动后才安装，也能在下次截图时被检测到。
    注意：在同一个进程中 sys.path 不变时重试不会成功，主要用于
    记录更详细的错误信息以便诊断。
    """
    global _Image, _pillow_error
    if _Image is not None:
        return True
    try:
        from PIL import Image as _Image_mod  # type: ignore[import-untyped]

        _Image = _Image_mod
        _pillow_error = None
        return True
    except ImportError as exc:
        _pillow_error = f"Pillow 未安装或 Python 找不到: {exc}"
        return False
    except Exception as exc:  # noqa: BLE001
        # Windows 上常见 DLL 加载失败（如缺失 VC 运行时）
        _pillow_error = f"Pillow 加载失败: {type(exc).__name__}: {exc}"
        return False


def get_pillow_diagnostic() -> dict[str, Any]:
    """返回 Pillow 诊断信息，供 get_status 等场景使用。"""
    info: dict[str, Any] = {
        "pillow_loaded": _Image is not None,
        "pillow_error": _pillow_error,
        "python_executable": sys.executable,
    }
    if _Image is not None:
        try:
            info["pillow_version"] = _Image.__version__  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    return info


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

    # 启动时尝试加载 Pillow，失败不阻塞；后续 screenshot_available() 会重试
    _init_pillow()


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
        """检查截图功能是否可用。

        优先使用 Pillow（Image.grab），其次回退到 Win32 BitBlt。
        只要有任意一种方式可用就返回 True。
        """
        return _init_pillow() or (_IS_WINDOWS and _win32gui is not None and _win32ui is not None)

    @staticmethod
    def screenshot_method() -> str:
        """返回当前截图方式：'pillow' / 'win32_bitblt' / 'unavailable'。"""
        if _init_pillow():
            return "pillow"
        if _IS_WINDOWS and _win32gui is not None and _win32ui is not None:
            return "win32_bitblt"
        return "unavailable"

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

        截图策略：
        1. 优先使用 Pillow Image.grab()（简单可靠）
        2. Pillow 不可用时，回退到 Win32 BitBlt（需 pywin32）
        3. 都不可用则抛出详细错误信息

        Args:
            hwnd: 窗口句柄。为 None 时截取全屏。
            region: 截取区域 (left, top, right, bottom)，相对于窗口。
                    仅当 hwnd 不为 None 时有效。
            format: 图片格式，默认 png。

        Returns:
            base64 编码的图片字符串。
        """
        if not self.screenshot_available():
            # 构建详细错误信息帮助诊断
            parts = ["截图功能不可用。"]
            if _pillow_error:
                parts.append(f"Pillow: {_pillow_error}")
            else:
                parts.append("Pillow: 未加载")
            if not (_IS_WINDOWS and _win32ui is not None):
                parts.append("Win32 BitBlt 后备: pywin32 未安装")
            parts.append(f"当前 Python: {sys.executable}")
            parts.append("提示: 请确保 Pillow 安装在 MyClaw 使用的 Python 环境中，"
                         "而非系统 Python 或其他虚拟环境。")
            raise RuntimeError(" ".join(parts))

        if hwnd is not None:
            return self._screenshot_window(hwnd, region, format)
        return self._screenshot_fullscreen(format)

    def _screenshot_window(
        self,
        hwnd: int,
        region: tuple[int, int, int, int] | None,
        format: str,
    ) -> str:
        """截取指定窗口。优先 Pillow，失败后回退 Win32 BitBlt。"""
        self._ensure_windows()

        # 获取窗口矩形
        left, top, right, bottom = _win32gui.GetWindowRect(hwnd)

        if region:
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

        # 策略 1: Pillow Image.grab()
        if _Image is not None:
            try:
                img = _Image.grab(bbox=(abs_left, abs_top, abs_right, abs_bottom))
                buf = io.BytesIO()
                img.save(buf, format=format.upper())
                return base64.b64encode(buf.getvalue()).decode("utf-8")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Pillow Image.grab() 失败，尝试 Win32 BitBlt 后备: %s", exc)

        # 策略 2: Win32 BitBlt（不需要 Pillow）
        return self._screenshot_bitblt(
            hwnd, abs_left, abs_top, capture_width, capture_height, format,
        )

    def _screenshot_fullscreen(self, format: str) -> str:
        """截取全屏。优先 Pillow，失败后回退 Win32 BitBlt。"""
        # 策略 1: Pillow
        if _Image is not None:
            try:
                img = _Image.grab()
                buf = io.BytesIO()
                img.save(buf, format=format.upper())
                return base64.b64encode(buf.getvalue()).decode("utf-8")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Pillow 全屏截图失败，尝试 Win32 BitBlt 后备: %s", exc)

        # 策略 2: Win32 BitBlt 全屏
        self._ensure_windows()
        # 获取屏幕尺寸
        screen_width = _win32gui.GetSystemMetrics(0)  # SM_CXSCREEN
        screen_height = _win32gui.GetSystemMetrics(1)  # SM_CYSCREEN
        hwnd_desktop = _win32gui.GetDesktopWindow()
        return self._screenshot_bitblt(
            hwnd_desktop, 0, 0, screen_width, screen_height, format,
        )

    def _screenshot_bitblt(
        self,
        hwnd: int,
        abs_left: int,
        abs_top: int,
        width: int,
        height: int,
        format: str,
    ) -> str:
        """使用 Win32 BitBlt 截图，生成 BMP 再用 base64 编码。

        不依赖 Pillow，仅使用 pywin32（win32gui/win32ui/win32con）。
        输出格式固定为 BMP（format 参数被忽略）。
        """
        self._ensure_windows()
        if _win32ui is None:
            raise RuntimeError("Win32 BitBlt 后备不可用: pywin32 (win32ui) 未安装")

        # 获取窗口 DC
        hwnd_dc = _win32gui.GetWindowDC(hwnd)
        mfc_dc = _win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()

        # 创建位图
        save_bitmap = _win32ui.CreateBitmap()
        save_bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(save_bitmap)

        # BitBlt 拷贝
        save_dc.BitBlt(
            (0, 0), (width, height), mfc_dc,
            (abs_left, abs_top), _win32con.SRCCOPY,
        )

        # 将位图转为 BMP 字节
        bmp_info = save_bitmap.GetInfo()
        bmp_bits = save_bitmap.GetBitmapBits(True)

        # 构造 BMP 文件头
        bmp_header_size = 40  # BITMAPINFOHEADER
        pixel_data_size = len(bmp_bits)
        file_header = struct.pack(
            "<2sIHHI",
            b"BM",
            14 + bmp_header_size + pixel_data_size,  # 文件总大小
            0, 0,  # 保留
            14 + bmp_header_size,  # 像素数据偏移
        )
        info_header = struct.pack(
            "<IiiHHIIiiII",
            bmp_header_size,
            bmp_info["bmWidth"],
            bmp_info["bmHeight"],
            1,  # planes
            bmp_info["bmPlanes"] * 8,  # bits per pixel (近似)
            0,  # compression
            pixel_data_size,
            0, 0,  # pixels per meter
            0, 0,  # colors
        )

        bmp_data = file_header + info_header + bmp_bits

        # 清理资源
        _win32gui.DeleteObject(save_bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        _win32gui.ReleaseDC(hwnd, hwnd_dc)

        # 如果 Pillow 可用，尝试转成目标格式；否则返回 BMP 的 base64
        if _Image is not None:
            img = _Image.open(io.BytesIO(bmp_data))
            buf = io.BytesIO()
            img.save(buf, format=format.upper())
            return base64.b64encode(buf.getvalue()).decode("utf-8")

        # 无 Pillow，返回 BMP base64，并在方法名中标注
        return base64.b64encode(bmp_data).decode("utf-8")

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