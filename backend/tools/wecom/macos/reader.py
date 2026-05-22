"""macOS 企业微信窗口自动化核心类。

通过 pyobjc (Quartz/AppKit) + pyautogui + Pillow 实现企微窗口操作。

注意：
- 需要授予辅助功能权限（系统偏好设置 → 隐私 → 辅助功能）
- macOS 上企业微信的进程名/窗口标题可能与 Windows 不同，
  默认按 owner_name 精确匹配 "企业微信" 或 "WeCom"
"""
from __future__ import annotations

import os
import subprocess
import time
import logging
import platform
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# macOS-only 依赖，条件导入
# ---------------------------------------------------------------------------
_IS_MACOS = platform.system() == "Darwin"

_Quartz: Any = None
_NSWorkspace: Any = None
_NSRunningApplication: Any = None
_NSApplicationActivateIgnoringOtherApps: Any = None
_pyautogui: Any = None
_pyperclip: Any = None


def _init_deps() -> bool:
    """初始化 macOS 依赖，返回是否成功。"""
    global _Quartz, _NSWorkspace, _NSRunningApplication
    global _NSApplicationActivateIgnoringOtherApps
    global _pyautogui, _pyperclip

    if not _IS_MACOS:
        return False

    ok = True

    try:
        import Quartz as _Q  # type: ignore[import-untyped]
        _Quartz = _Q
    except Exception as exc:  # noqa: BLE001
        logger.warning("pyobjc-framework-Quartz 导入失败: %s", exc)
        ok = False

    try:
        from AppKit import NSWorkspace as _NSW  # type: ignore[import-untyped]
        from AppKit import NSRunningApplication as _NSRA  # type: ignore[import-untyped]
        from AppKit import NSApplicationActivateIgnoringOtherApps as _NSAA  # type: ignore[import-untyped]
        _NSWorkspace = _NSW
        _NSRunningApplication = _NSRA
        _NSApplicationActivateIgnoringOtherApps = _NSAA
    except Exception as exc:  # noqa: BLE001
        logger.warning("pyobjc-framework-Cocoa 导入失败: %s", exc)
        ok = False

    try:
        import pyautogui as _pag  # type: ignore[import-untyped]
        _pyautogui = _pag
        _pyautogui.FAILSAFE = False  # 与 Windows 版保持一致
    except ImportError:
        logger.warning("pyautogui 未安装")
        ok = False

    try:
        import pyperclip as _pc  # type: ignore[import-untyped]
        _pyperclip = _pc
    except ImportError:
        logger.warning("pyperclip 未安装")

    return ok


if _IS_MACOS:
    _init_deps()


# ---------------------------------------------------------------------------
# macOS 企业微信窗口名称匹配规则
#
# macOS 上企业微信可能的表现：
# - kCGWindowOwnerName: "企业微信" 或 "WeCom"
# - kCGWindowName: 可能为主窗口标题
#
# 如果实际不符，修改此处即可。
# ---------------------------------------------------------------------------
_WECOM_OWNER_NAMES = {"企业微信", "WeCom"}


def _is_wecom_window(owner_name: str, title: str) -> bool:
    """判断窗口是否属于企业微信。"""
    owner_lower = owner_name.lower()
    # 精确匹配 owner name
    for name in _WECOM_OWNER_NAMES:
        if name.lower() == owner_lower:
            return True
    # 模糊匹配：owner 包含 "企业微信" 或 "wecom"
    if "企业微信" in owner_name or "wecom" in owner_lower:
        return True
    return False


class MacWeComReader:
    """macOS 企业微信窗口自动化操作器。

    接口与 Windows 版 WeComReader 保持一致：
    - connect()
    - activate()
    - search_and_open_chat(name)
    - scroll_to_latest()
    - send_message(text)
    - screenshot_window(save_path)
    """

    def __init__(self) -> None:
        self._ensure_available()
        self.window_id: int | None = None  # CGWindowID
        self.pid: int | None = None
        self._bounds: tuple[float, float, float, float] | None = None  # (x, y, w, h)

    # ------------------------------------------------------------------
    # 前置检查
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_available() -> None:
        """确保运行在 macOS 且核心依赖已安装。"""
        if not _IS_MACOS:
            raise RuntimeError("wecom macOS 实现仅支持 macOS 平台")
        if _Quartz is None:
            raise RuntimeError(
                "pyobjc-framework-Quartz 未安装，请运行: pip install pyobjc-framework-Quartz"
            )

    @staticmethod
    def _ensure_pyautogui() -> None:
        """确保 pyautogui 可用，尝试懒加载。"""
        global _pyautogui
        if _pyautogui is not None:
            return
        try:
            import pyautogui as _pag  # type: ignore[import-untyped]
            _pyautogui = _pag
            _pyautogui.FAILSAFE = False
        except ImportError:
            raise RuntimeError(
                "pyautogui 未安装，请运行: pip install pyautogui"
            )

    # ------------------------------------------------------------------
    # 窗口查找
    # ------------------------------------------------------------------

    def _find_wecom_windows(self) -> list[dict[str, Any]]:
        """查找所有企业微信窗口。

        Returns:
            匹配的窗口信息列表，每个包含 window_id, pid, owner, title, bounds。
        """
        window_list = _Quartz.CGWindowListCopyWindowInfo(
            _Quartz.kCGWindowListOptionOnScreenOnly
            | _Quartz.kCGWindowListExcludeDesktopElements,
            _Quartz.kCGNullWindowID,
        )
        if window_list is None:
            return []

        results: list[dict[str, Any]] = []
        for win_dict in window_list:
            try:
                owner = win_dict.get("kCGWindowOwnerName", "") or ""
                title = win_dict.get("kCGWindowName", "") or ""
                layer = win_dict.get("kCGWindowLayer", 0)
                pid = win_dict.get("kCGWindowOwnerPID", 0)
                wid = win_dict.get("kCGWindowNumber", 0)
                bounds_dict = win_dict.get("kCGWindowBounds", {})
            except Exception:  # noqa: BLE001
                continue

            # 只保留应用层窗口（layer == 0）
            if layer != 0:
                continue

            if _is_wecom_window(owner, title):
                bounds = (
                    bounds_dict.get("X", 0),
                    bounds_dict.get("Y", 0),
                    bounds_dict.get("Width", 0),
                    bounds_dict.get("Height", 0),
                )
                results.append({
                    "window_id": wid,
                    "pid": pid,
                    "owner": owner,
                    "title": title,
                    "bounds": bounds,
                })

        return results

    def _refresh_bounds(self) -> None:
        """刷新窗口 bounds（窗口可能被移动或缩放）。"""
        if self.window_id is None:
            return

        window_list = _Quartz.CGWindowListCopyWindowInfo(
            _Quartz.kCGWindowListOptionOnScreenOnly
            | _Quartz.kCGWindowListExcludeDesktopElements,
            _Quartz.kCGNullWindowID,
        )
        if window_list is None:
            return

        for win_dict in window_list:
            try:
                wid = win_dict.get("kCGWindowNumber", 0)
                if wid == self.window_id:
                    bounds_dict = win_dict.get("kCGWindowBounds", {})
                    self._bounds = (
                        bounds_dict.get("X", 0),
                        bounds_dict.get("Y", 0),
                        bounds_dict.get("Width", 0),
                        bounds_dict.get("Height", 0),
                    )
                    return
            except Exception:  # noqa: BLE001
                continue

    # ------------------------------------------------------------------
    # 窗口管理
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """查找并连接已运行的企业微信窗口。

        Returns:
            True 表示连接成功。
        """
        windows = self._find_wecom_windows()

        if not windows:
            logger.error("未找到企业微信窗口")
            return False

        # 优先选择有标题的窗口（主窗口）
        target = None
        for win in windows:
            if win["title"]:
                target = win
                break
        if target is None:
            target = windows[0]

        self.window_id = target["window_id"]
        self.pid = target["pid"]
        self._bounds = target["bounds"]

        logger.info(
            "找到企微窗口: window_id=%s, pid=%s, owner=%s, title=%s",
            self.window_id, self.pid, target["owner"], target["title"],
        )

        # 激活窗口
        self.activate()
        logger.info("连接企微成功")
        return True

    @property
    def hwnd(self) -> int | None:
        """兼容 Windows 版接口：hwnd 对应 macOS 的 window_id。"""
        return self.window_id

    def activate(self) -> bool:
        """强制激活窗口到前台。

        Returns:
            True 表示窗口已在前台。
        """
        if self.window_id is None or self.pid is None:
            return False

        try:
            apps = _NSWorkspace.sharedWorkspace().runningApplications()
            for app in apps:
                if app.processIdentifier() == self.pid:
                    app.activateWithOptions_(_NSApplicationActivateIgnoringOtherApps)
                    time.sleep(0.3)
                    break
        except Exception as exc:  # noqa: BLE001
            logger.warning("activate 失败: %s", exc)

        # 兜底：点击窗口中心
        self._ensure_pyautogui()
        self._refresh_bounds()
        if self._bounds:
            x, y, w, h = self._bounds
            cx = x + w / 2
            cy = y + h / 2
            try:
                _pyautogui.click(cx, cy)
                time.sleep(0.3)
            except Exception:  # noqa: BLE001
                pass

        logger.debug("窗口已激活")
        time.sleep(0.3)
        return True

    # ------------------------------------------------------------------
    # 聊天操作
    # ------------------------------------------------------------------

    def search_and_open_chat(self, name: str) -> bool:
        """搜索联系人/群聊并打开聊天窗口。

        macOS 企微快捷键（来自官方文档）：
        - Cmd+1~8   切换左侧 Tab（对应 Windows Ctrl+1~8）
        - Cmd+F     激活搜索框（对应 Windows Ctrl+F）
        - Cmd+V     粘贴内容
        - Enter     确认/打开搜索结果
        - Escape    关闭搜索

        Args:
            name: 搜索关键词（群名/联系人名）。

        Returns:
            True 表示操作成功。
        """
        if self.window_id is None:
            return False

        self._ensure_pyautogui()

        # 确保窗口在前台，避免键盘操作发到其他应用
        self.activate()
        time.sleep(0.3)

        # 切到消息栏（Cmd+1 = 切换到第一个左侧 Tab，即消息页）
        _pyautogui.hotkey("command", "1")
        time.sleep(0.3)

        # 激活搜索框（Cmd+F）
        _pyautogui.hotkey("command", "f")
        time.sleep(0.5)

        # 粘贴搜索词（Cmd+V）
        _pyperclip.copy(name)
        time.sleep(0.3)
        _pyautogui.hotkey("command", "v")
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
        """滚动聊天区域到最新消息。

        macOS 企微快捷键（来自官方文档）：
        - PageDown  向下查看聊天内容
        - PageUp    向上查看聊天内容
        - 注：官方"到消息列表的底部"无快捷键，用多次 PageDown 替代
        """
        if self.window_id is None:
            return

        self._ensure_pyautogui()

        # 先激活窗口到前台，确保 pyautogui 键盘事件发到企微窗口
        self.activate()
        time.sleep(0.3)

        self._refresh_bounds()
        if not self._bounds:
            return

        x, y, w, h = self._bounds

        # 点击聊天区域中间，确保焦点在消息列表
        click_x = x + int(w * 0.55)
        click_y = y + int(h * 0.4)
        _pyautogui.click(click_x, click_y)
        time.sleep(0.5)

        for _ in range(10):
            _pyautogui.press("pgdn")
            time.sleep(0.15)

        logger.info("已滚动到最新消息")

    def send_message(self, text: str) -> bool:
        """在当前打开的聊天中发送一条消息。

        macOS 企微快捷键（来自官方文档）：
        - Enter          发送消息（也可 Cmd+Enter，取决于设置）
        - Cmd+V          粘贴内容
        - Cmd+A          全选（标准 macOS 行为）

        Args:
            text: 消息内容。

        Returns:
            True 表示发送成功。
        """
        if self.window_id is None:
            return False

        self._ensure_pyautogui()
        self.activate()
        time.sleep(0.3)

        self._refresh_bounds()
        if not self._bounds:
            logger.error("无法获取窗口 bounds")
            return False

        x, y, w, h = self._bounds

        # 点击输入框
        input_x = x + int(w * 0.6)
        input_y = y + int(h * 0.88)
        _pyautogui.click(input_x, input_y)
        time.sleep(0.5)

        # 清空输入框 (Cmd+A → Delete)
        _pyautogui.hotkey("command", "a")
        time.sleep(0.1)
        _pyautogui.press("delete")
        time.sleep(0.2)

        # 粘贴消息（Cmd+V）
        _pyperclip.copy(text)
        time.sleep(0.2)
        _pyautogui.hotkey("command", "v")
        time.sleep(1.0)

        # Enter 发送
        _pyautogui.press("enter")
        time.sleep(0.5)

        logger.info("已发送消息: %s...", text[:50])
        return True

    # ------------------------------------------------------------------
    # 截图
    # ------------------------------------------------------------------

    def screenshot_window(self, save_path: str | None = None) -> str:
        """截取企微窗口。

        截图策略（按优先级尝试）：
        1. screencapture -l <windowid>  （macOS 原生命令，最可靠）
        2. screencapture -R x,y,w,h    （区域截图）
        3. Quartz.CGWindowListCreateImage（兜底）

        Args:
            save_path: 保存路径。None 则使用临时文件。

        Returns:
            截图文件路径。
        """
        if self.window_id is None:
            raise RuntimeError("未连接企微窗口")

        self.activate()
        time.sleep(0.3)

        if save_path is None:
            os.makedirs(tempfile.gettempdir(), exist_ok=True)
            save_path = os.path.join(
                tempfile.gettempdir(), f"wecom_screenshot_{int(time.time())}.png"
            )

        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)

        # --- 方式 1: screencapture -l <windowid>（按窗口 ID 截取）---
        try:
            result = subprocess.run(
                ["screencapture", "-l", str(self.window_id), "-o", "-x", save_path],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and os.path.isfile(save_path) and os.path.getsize(save_path) > 0:
                logger.info("截图保存 (screencapture -l): %s", save_path)
                return save_path
            logger.debug("screencapture -l 失败: rc=%d, stderr=%s", result.returncode, result.stderr)
        except Exception as exc:  # noqa: BLE001
            logger.debug("screencapture -l 异常: %s", exc)

        # --- 方式 2: screencapture -R x,y,w,h（按区域截取）---
        self._refresh_bounds()
        if self._bounds:
            x, y, w, h = self._bounds
            if w > 0 and h > 0:
                try:
                    result = subprocess.run(
                        ["screencapture", "-R", f"{int(x)},{int(y)},{int(w)},{int(h)}", "-x", save_path],
                        capture_output=True, text=True, timeout=5,
                    )
                    if result.returncode == 0 and os.path.isfile(save_path) and os.path.getsize(save_path) > 0:
                        logger.info("截图保存 (screencapture -R): %s (%dx%d)", save_path, w, h)
                        return save_path
                    logger.debug("screencapture -R 失败: rc=%d, stderr=%s", result.returncode, result.stderr)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("screencapture -R 异常: %s", exc)

        # --- 方式 3: Quartz.CGWindowListCreateImage（兜底）---
        if self._bounds:
            x, y, w, h = self._bounds
            if w > 0 and h > 0:
                try:
                    window_rect = _Quartz.CGRectMake(x, y, w, h)
                    image_ref = _Quartz.CGWindowListCreateImage(
                        window_rect,
                        _Quartz.kCGWindowListOptionIncludingWindow,
                        self.window_id,
                        _Quartz.kCGWindowImageDefault,
                    )
                    if image_ref is not None:
                        url = _Quartz.CFURLCreateFromFileSystemRepresentation(
                            None, save_path.encode("utf-8"), len(save_path.encode("utf-8")), False
                        )
                        dest = _Quartz.CGImageDestinationCreateWithURL(url, "public.png", 1, None)
                        if dest is not None:
                            _Quartz.CGImageDestinationAddImage(dest, image_ref, None)
                            if _Quartz.CGImageDestinationFinalize(dest):
                                logger.info("截图保存 (Quartz): %s (%dx%d)", save_path, w, h)
                                return save_path
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Quartz 截图异常: %s", exc)

        raise RuntimeError(
            "所有截图方式均失败。请确认已授予屏幕录制权限 "
            "（系统偏好设置 → 隐私与安全性 → 屏幕录制），并重启应用后重试。"
        )
