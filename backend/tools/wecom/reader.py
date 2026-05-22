"""企业微信窗口自动化核心类。

通过 pywinauto + pyautogui + ctypes PrintWindow 实现企微窗口操作，
不依赖屏幕截图（PrintWindow 可在后台抓取窗口内容）。
"""
from __future__ import annotations

import os
import time
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Windows-only 模块，延迟导入
_win32gui: Any = None
_win32con: Any = None
_win32api: Any = None
_pyautogui: Any = None
_pyperclip: Any = None
_ctypes: Any = None

_PLATFORM_OK = True


def _ensure_imports() -> None:
    """延迟导入 Windows 依赖，非 Windows 平台直接报错。"""
    global _win32gui, _win32con, _win32api, _pyautogui, _pyperclip, _ctypes, _PLATFORM_OK

    import platform
    if platform.system() != "Windows":
        _PLATFORM_OK = False
        raise RuntimeError("wecom 工具仅支持 Windows 平台")

    if _win32gui is not None:
        return

    import ctypes
    import ctypes.wintypes
    import win32api
    import win32con
    import win32gui
    import pyautogui
    import pyperclip
    from pywinauto import Application, findwindows  # noqa: F401

    _ctypes = ctypes
    _win32gui = win32gui
    _win32con = win32con
    _win32api = win32api
    _pyautogui = pyautogui
    _pyperclip = pyperclip


def _make_bitmap_info_header(w: int, h: int) -> Any:
    """创建 BITMAPINFOHEADER 结构体（用于 GetDIBits）。

    Args:
        w: 位图宽度。
        h: 位图高度。

    Returns:
        BITMAPINFOHEADER ctypes Structure 实例。
    """
    class BITMAPINFOHEADER(_ctypes.Structure):  # type: ignore[misc]
        _fields_ = [
            ("biSize", _ctypes.wintypes.DWORD),
            ("biWidth", _ctypes.wintypes.LONG),
            ("biHeight", _ctypes.wintypes.LONG),
            ("biPlanes", _ctypes.wintypes.WORD),
            ("biBitCount", _ctypes.wintypes.WORD),
            ("biCompression", _ctypes.wintypes.DWORD),
            ("biSizeImage", _ctypes.wintypes.DWORD),
            ("biXPelsPerMeter", _ctypes.wintypes.LONG),
            ("biYPelsPerMeter", _ctypes.wintypes.LONG),
            ("biClrUsed", _ctypes.wintypes.DWORD),
            ("biClrImportant", _ctypes.wintypes.DWORD),
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = _ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0
    return bmi


class WeComReader:
    """企业微信窗口自动化操作器。

    核心能力：
    - 连接企微窗口（connect）
    - 搜索并打开聊天（search_and_open_chat）
    - 滚动到最新消息（scroll_to_latest）
    - PrintWindow 截图（screenshot_window）
    - 发送消息（send_message）
    """

    def __init__(self) -> None:
        _ensure_imports()
        self.app: Any = None
        self.dlg: Any = None
        self.hwnd: int | None = None

    # ------------------------------------------------------------------
    # 窗口管理
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """查找并连接已运行的企业微信窗口。

        Returns:
            True 表示连接成功。
        """
        from pywinauto import Application, findwindows

        try:
            handles = findwindows.find_windows(
                title="企业微信",
                class_name="WeWorkWindow",
                visible_only=True,
            )
        except Exception as e:
            logger.error("查找企微窗口失败: %s", e)
            return False

        if not handles:
            logger.error("未找到企业微信窗口")
            return False

        self.hwnd = handles[0]
        logger.info("找到企微窗口: hwnd=%s", self.hwnd)

        try:
            self.app = Application(backend="uia").connect(handle=self.hwnd)
            self.dlg = self.app.window(handle=self.hwnd)
            self.dlg.wait("ready", timeout=5)
            # 最大化窗口
            try:
                _win32gui.ShowWindow(self.hwnd, _win32con.SW_SHOWMAXIMIZED)
            except Exception:
                try:
                    self.dlg.maximize()
                except Exception:
                    self.dlg.restore()
            self.dlg.set_focus()
            logger.info("连接企微成功")
            return True
        except Exception as e:
            logger.error("连接企微失败: %s", e)
            return False

    def activate(self) -> bool:
        """强制激活窗口到前台。

        使用 AttachThreadInput 绕过 Windows 前台窗口限制。

        Returns:
            True 表示窗口已在前台。
        """
        if not self.hwnd:
            return False

        import threading

        # 置顶 + 最大化
        try:
            _win32gui.SetWindowPos(
                self.hwnd, _win32con.HWND_TOPMOST, 0, 0, 0, 0,
                _win32con.SWP_NOMOVE | _win32con.SWP_NOSIZE | _win32con.SWP_SHOWWINDOW,
            )
            time.sleep(0.1)
            _win32gui.SetWindowPos(
                self.hwnd, _win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                _win32con.SWP_NOMOVE | _win32con.SWP_NOSIZE | _win32con.SWP_SHOWWINDOW,
            )
        except Exception:
            pass

        try:
            _win32gui.ShowWindow(self.hwnd, _win32con.SW_SHOWMAXIMIZED)
        except Exception:
            pass

        for _ in range(3):
            fg = _win32gui.GetForegroundWindow()
            if fg == self.hwnd:
                break

            try:
                _win32gui.SetForegroundWindow(self.hwnd)
                time.sleep(0.2)
                fg = _win32gui.GetForegroundWindow()
                if fg == self.hwnd:
                    break
            except Exception:
                pass

            try:
                fg_thread = _win32api.GetWindowThreadProcessId(fg)[0]
                my_thread = threading.current_thread().ident
                _win32api.AttachThreadInput(my_thread, fg_thread, True)
                try:
                    _win32gui.SetForegroundWindow(self.hwnd)
                    time.sleep(0.2)
                finally:
                    _win32api.AttachThreadInput(my_thread, fg_thread, False)

                fg = _win32gui.GetForegroundWindow()
                if fg == self.hwnd:
                    break
            except Exception:
                pass

            try:
                _win32gui.BringWindowToTop(self.hwnd)
                _win32gui.ShowWindow(self.hwnd, _win32con.SW_SHOWMAXIMIZED)
            except Exception:
                pass
            time.sleep(0.3)

        # 物理点击兜底
        fg = _win32gui.GetForegroundWindow()
        if fg != self.hwnd:
            try:
                rect = _win32gui.GetWindowRect(self.hwnd)
                cx = (rect[0] + rect[2]) // 2
                cy = (rect[1] + rect[3]) // 2
                _pyautogui.click(cx, cy)
                time.sleep(0.5)
            except Exception:
                pass

        fg = _win32gui.GetForegroundWindow()
        ok = fg == self.hwnd
        if ok:
            logger.debug("窗口已激活到前台")
        else:
            logger.warning("窗口可能未在前台 (fg=%s, target=%s)", fg, self.hwnd)
        time.sleep(0.3)
        return ok

    # ------------------------------------------------------------------
    # 聊天操作
    # ------------------------------------------------------------------

    def search_and_open_chat(self, name: str) -> bool:
        """搜索联系人/群聊并打开聊天窗口。

        Args:
            name: 搜索关键词（群名/联系人名）。

        Returns:
            True 表示操作成功。
        """
        if not self.hwnd:
            return False

        _pyautogui.FAILSAFE = False

        # 确保窗口在前台，避免键盘操作发到其他应用
        self.activate()
        time.sleep(0.3)

        # 切到消息栏
        _pyautogui.hotkey("ctrl", "1")
        time.sleep(0.3)

        # Ctrl+F 搜索
        _pyautogui.hotkey("ctrl", "f")
        time.sleep(0.5)

        # 粘贴搜索词
        _pyperclip.copy(name)
        time.sleep(0.3)
        _pyautogui.hotkey("ctrl", "v")
        time.sleep(2.0)

        # 回车打开第一个结果
        logger.info("打开搜索结果: %s", name)
        _pyautogui.press("enter")
        time.sleep(1.5)

        # ESC 关闭搜索
        _pyautogui.press("escape")
        time.sleep(0.3)

        return True

    def scroll_to_latest(self) -> None:
        """滚动聊天区域到最新消息（PageDown x10）。"""
        if not self.hwnd:
            return

        _pyautogui.FAILSAFE = False

        # 先激活窗口到前台，确保 pyautogui 键盘事件发到企微窗口
        self.activate()
        time.sleep(0.3)

        # 点击聊天区域中间，确保焦点在消息列表
        rect = _win32gui.GetWindowRect(self.hwnd)
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]

        click_x = rect[0] + int(w * 0.55)
        click_y = rect[1] + int(h * 0.4)
        _pyautogui.click(click_x, click_y)
        time.sleep(0.5)

        for _ in range(10):
            _pyautogui.press("pgdn")
            time.sleep(0.15)

        logger.info("已滚动到最新消息")

    def send_message(self, text: str) -> bool:
        """在当前打开的聊天中发送一条消息。

        Args:
            text: 消息内容。

        Returns:
            True 表示发送成功。
        """
        if not self.hwnd:
            return False

        _pyautogui.FAILSAFE = False

        self.activate()
        time.sleep(0.3)

        rect = _win32gui.GetWindowRect(self.hwnd)
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]

        # 点击输入框
        input_x = rect[0] + int(w * 0.6)
        input_y = rect[1] + int(h * 0.88)
        _pyautogui.click(input_x, input_y)
        time.sleep(0.5)

        # 清空输入框
        _pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)
        _pyautogui.press("delete")
        time.sleep(0.2)

        # 粘贴消息
        _pyperclip.copy(text)
        time.sleep(0.2)
        _pyautogui.hotkey("ctrl", "v")
        time.sleep(1.0)

        # 回车发送
        _pyautogui.press("enter")
        time.sleep(0.5)

        logger.info("已发送消息: %s...", text[:50])
        return True

    # ------------------------------------------------------------------
    # 截图
    # ------------------------------------------------------------------

    def screenshot_window(self, save_path: str | None = None) -> str:
        """用 PrintWindow 截取企微窗口（不依赖屏幕访问）。

        Args:
            save_path: 保存路径。None 则使用临时文件。

        Returns:
            截图文件路径。
        """
        if not self.hwnd:
            raise RuntimeError("未连接企微窗口")

        from PIL import Image

        self.activate()
        time.sleep(0.3)

        rect = _win32gui.GetWindowRect(self.hwnd)
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]

        user32 = _ctypes.windll.user32
        gdi32 = _ctypes.windll.gdi32

        # 64-bit safe: HWND/HDC/HBITMAP 在 x64 Windows 上可超过 32-bit 范围，
        # 必须通过 argtypes/restype 声明为 c_void_p（指针宽度），
        # 否则 ctypes 默认按 c_int 转换会抛出 OverflowError: int too long to convert。
        _cv = _ctypes.c_void_p
        _cu = _ctypes.c_uint
        _ci = _ctypes.c_int

        user32.GetWindowDC.argtypes = [_cv]
        user32.GetWindowDC.restype  = _cv
        user32.PrintWindow.argtypes = [_cv, _cv, _cu]
        user32.ReleaseDC.argtypes   = [_cv, _cv]

        gdi32.CreateCompatibleDC.argtypes     = [_cv]
        gdi32.CreateCompatibleDC.restype      = _cv
        gdi32.CreateCompatibleBitmap.argtypes = [_cv, _ci, _ci]
        gdi32.CreateCompatibleBitmap.restype  = _cv
        gdi32.SelectObject.argtypes           = [_cv, _cv]
        gdi32.GetDIBits.argtypes = [
            _cv, _cv, _cu, _cu, _ctypes.c_void_p, _ctypes.c_void_p, _cu,
        ]
        gdi32.DeleteObject.argtypes = [_cv]
        gdi32.DeleteDC.argtypes     = [_cv]

        hwnd_c = _cv(self.hwnd)

        hdc = user32.GetWindowDC(hwnd_c)
        hdc_mem = gdi32.CreateCompatibleDC(hdc)
        h_bitmap = gdi32.CreateCompatibleBitmap(hdc, w, h)
        gdi32.SelectObject(hdc_mem, h_bitmap)

        try:
            # PrintWindow: flag 2 = PW_RENDERFULLCONTENT
            user32.PrintWindow(hwnd_c, hdc_mem, 2)

            # GetDIBits
            bmi = _make_bitmap_info_header(w, h)
            pixel_buf = _ctypes.create_string_buffer(w * h * 4)
            rows = gdi32.GetDIBits(
                hdc_mem, h_bitmap, 0, h, pixel_buf,
                _ctypes.byref(bmi), 0,
            )

            if rows <= 0:
                raise RuntimeError("GetDIBits returned 0 rows")

            img = Image.frombuffer("RGB", (w, h), pixel_buf, "raw", "BGRX", 0, 1)
        finally:
            # 确保资源释放（即使 GetDIBits 或 frombuffer 异常）
            gdi32.DeleteObject(h_bitmap)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(hwnd_c, hdc)

        # 保存
        if save_path is None:
            import tempfile
            os.makedirs(tempfile.gettempdir(), exist_ok=True)
            save_path = os.path.join(
                tempfile.gettempdir(), f"wecom_screenshot_{int(time.time())}.png"
            )

        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        img.save(save_path)
        logger.info("截图保存: %s (%dx%d)", save_path, w, h)
        return save_path
