"""系统级最顶层倒计时通知模块。

在桌面自动化操作前弹出倒计时通知条（屏幕顶部），
操作后弹出完成提示条（屏幕底部）。
使用 Tkinter 实现系统最顶层窗口，支持 Windows 和 macOS。
"""
from __future__ import annotations

import logging
import platform
import subprocess
import threading
import time
from typing import Any, Callable, Literal

logger = logging.getLogger(__name__)

_IS_MACOS = platform.system() == "Darwin"
_IS_WINDOWS = platform.system() == "Windows"

# 默认倒计时秒数
DEFAULT_COUNTDOWN_SECONDS = 3
# 操作后提示自动关闭秒数
DEFAULT_NOTIFY_SECONDS = 2

# 操作前需要倒计时通知的 action 集合
COUNTDOWN_ACTIONS = frozenset({"click", "type_text", "send_keys", "scroll"})


# ---------------------------------------------------------------------------
# Win32 强制置顶辅助
# ---------------------------------------------------------------------------

# Win32 API 常量
_HWND_TOPMOST = -1
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOACTIVATE = 0x0010


def _enforce_topmost_win32(root: Any, interval_ms: int = 200) -> None:
    """Windows: 用 Win32 API 强制窗口置顶并周期性刷新。

    借鉴 ``backend/tools/wecom/reader.py`` 中 ``activate()`` 的成熟方案，
    通过 ctypes 直接调用 SetWindowPos(HWND_TOPMOST) 实现比 Tkinter
    ``wm_attributes("-topmost")`` 更可靠的置顶效果。

    周期性刷新（默认 200ms）确保即使其他窗口抢走 topmost，
    也能在极短时间内恢复，对桌面自动化场景足够可靠。

    非 Windows 平台为空操作。

    Args:
        root: Tkinter 窗口实例。
        interval_ms: 刷新间隔（毫秒），默认 200ms。
    """
    if not _IS_WINDOWS:
        return

    try:
        import ctypes

        hwnd = root.winfo_id()
        if not hwnd:
            return

        user32 = ctypes.windll.user32

        # 64-bit 安全：HWND 在 x64 上可能超过 32-bit 范围
        user32.SetWindowPos.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = ctypes.c_int

        # 立即执行一次强制置顶
        user32.SetWindowPos(
            hwnd, _HWND_TOPMOST, 0, 0, 0, 0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE,
        )

        def _refresh() -> None:
            """周期性刷新 topmost，双保险。"""
            try:
                user32.SetWindowPos(
                    hwnd, _HWND_TOPMOST, 0, 0, 0, 0,
                    _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE,
                )
                # 双保险：同时用 Tkinter 方式刷新
                try:
                    root.wm_attributes("-topmost", True)
                except Exception:
                    pass
            except Exception:
                pass
            # 只要窗口还存在，就继续刷新
            try:
                if root.winfo_exists():
                    root.after(interval_ms, _refresh)
            except Exception:
                pass

        # 启动周期性刷新
        root.after(interval_ms, _refresh)

    except Exception as exc:
        logger.debug("Win32 topmost 增强失败（不影响基本功能）: %s", exc)


# ---------------------------------------------------------------------------
# 内部：Tkinter 窗口构建
# ---------------------------------------------------------------------------

def _build_countdown_window(
    action: str,
    detail: str,
    seconds: int,
    tool_name: str = "computer",
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[Any, list[int]]:
    """构建操作前倒计时窗口。

    Returns:
        (root, result_holder) — root 是 Tk 实例，result_holder[0] 存放退出码
        退出码：0=proceed（倒计时结束），1=skip，2=cancel
    """
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()  # 先隐藏，计算完位置再显示

    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()

    bar_width = 540
    bar_height = 54
    x = (screen_w - bar_width) // 2
    y = 40  # 屏幕顶部

    # 外层：带 2px 深色边框
    bg_color = "#fff3e0"
    border_color = "#e65100"
    text_color = "#bf360c"

    root.overrideredirect(True)
    root.configure(bg=border_color)
    root.geometry(f"{bar_width}x{bar_height}+{x}+{y}")
    root.wm_attributes("-topmost", True)

    # Win32 增强置顶：周期性刷新，确保始终在最前面
    _enforce_topmost_win32(root)

    # macOS: 设置窗口层级为浮动
    if _IS_MACOS:
        try:
            # NSFloatingWindowLevel = 3
            root.call("::tk::unsupported::MacWindowStyle", root, "move", "floating")
        except Exception:
            pass

    # 内层 frame（模拟边框效果）
    frame = tk.Frame(root, bg=bg_color)
    frame.pack(fill="both", expand=True, padx=2, pady=2)

    result_code = [0]  # 0=proceed, 1=skip, 2=cancel

    # 标题
    title_text = f"⏳ {seconds}秒后执行: {action}"
    if detail:
        title_text += f"  ({detail})"
    title_label = tk.Label(
        frame, text=title_text,
        font=("", 12, "bold"), fg=text_color, bg=bg_color, anchor="w",
    )
    title_label.pack(side="left", padx=(12, 8), fill="x", expand=True)

    # 倒计时数字
    countdown_label = tk.Label(
        frame, text=str(seconds), font=("", 16, "bold"),
        fg=border_color, bg=bg_color, width=3,
    )
    countdown_label.pack(side="left", padx=4)

    # 跳过按钮
    def on_skip() -> None:
        result_code[0] = 1
        root.destroy()

    skip_btn = tk.Button(
        frame, text="跳过", font=("", 10), command=on_skip,
        relief="flat", bg="#ffe0b2", fg=text_color,
        activebackground="#ffcc80", padx=8, pady=1, cursor="hand2",
    )
    skip_btn.pack(side="left", padx=3)

    # 取消按钮
    def on_cancel() -> None:
        result_code[0] = 2
        root.destroy()

    cancel_btn = tk.Button(
        frame, text="取消", font=("", 10), command=on_cancel,
        relief="flat", bg="#ffcdd2", fg="#c62828",
        activebackground="#ef9a9a", padx=8, pady=1, cursor="hand2",
    )
    cancel_btn.pack(side="left", padx=(3, 8))

    # 倒计时逻辑
    remaining = [seconds]

    def tick() -> None:
        if remaining[0] <= 0:
            root.destroy()
            return
        countdown_label.config(text=str(remaining[0]))
        remaining[0] -= 1

        # 通过事件回调通知前端
        if event_callback:
            try:
                event_callback({
                    "type": "countdown",
                    "tool": tool_name,
                    "action": action,
                    "remaining_seconds": remaining[0] + 1,
                })
            except Exception:
                pass

        root.after(1000, tick)

    root.after(100, lambda: countdown_label.config(text=str(seconds)))
    root.after(1000, tick)

    # 显示窗口
    root.deiconify()

    return root, result_code


def _build_notification_window(
    action: str,
    detail: str,
    success: bool,
    seconds: int,
) -> Any:
    """构建操作后提示窗口。"""
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()

    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()

    bar_width = 400
    bar_height = 46

    if success:
        bg_color = "#e8f5e9"
        border_color = "#2e7d32"
        text_color = "#1b5e20"
        icon = "✅"
    else:
        bg_color = "#fce4ec"
        border_color = "#c62828"
        text_color = "#b71c1c"
        icon = "❌"

    # 屏幕底部居中
    x = (screen_w - bar_width) // 2
    y = screen_h - bar_height - 60

    root.overrideredirect(True)
    root.configure(bg=border_color)
    root.geometry(f"{bar_width}x{bar_height}+{x}+{y}")
    root.wm_attributes("-topmost", True)

    # Win32 增强置顶：周期性刷新，确保始终在最前面
    _enforce_topmost_win32(root)

    if _IS_MACOS:
        try:
            root.call("::tk::unsupported::MacWindowStyle", root, "move", "floating")
        except Exception:
            pass

    frame = tk.Frame(root, bg=bg_color)
    frame.pack(fill="both", expand=True, padx=2, pady=2)

    title_text = f"{icon} {action} {'完成' if success else '失败'}"
    if detail:
        title_text += f"  ({detail})"

    label = tk.Label(
        frame, text=title_text,
        font=("", 12, "bold"), fg=text_color, bg=bg_color,
    )
    label.pack(expand=True, padx=12)

    root.deiconify()
    root.after(seconds * 1000, root.destroy)

    return root


# ---------------------------------------------------------------------------
# macOS fallback：osascript
# ---------------------------------------------------------------------------

def _macos_countdown_osascript(
    action: str,
    detail: str,
    seconds: int,
) -> str:
    """macOS fallback：用 osascript display dialog 实现倒计时。

    Returns:
        "proceed" / "skip" / "cancel"
    """
    message = f"⏳ {seconds}秒后执行: {action}"
    if detail:
        message += f"\\n({detail})"

    script = (
        f'display dialog "{message}" '
        f'buttons {{"取消", "跳过", "继续"}} '
        f'default button "继续" '
        f'giving up after {seconds}'
    )

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=seconds + 5,
        )
        output = result.stdout.strip()
        if "gave up" in output:
            return "proceed"
        if "跳过" in output:
            return "skip"
        if "取消" in output:
            return "cancel"
        return "proceed"
    except subprocess.TimeoutExpired:
        return "proceed"
    except Exception as exc:
        logger.warning("macOS osascript 倒计时失败: %s", exc)
        return "proceed"


def _macos_notify_osascript(action: str, detail: str, success: bool) -> None:
    """macOS fallback：用 osascript display notification 提示。"""
    icon = "✅" if success else "❌"
    message = f"{icon} {action} {'完成' if success else '失败'}"
    if detail:
        message += f" ({detail})"

    script = f'display notification "{message}" with title "MyClaw"'

    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, timeout=5,
        )
    except Exception as exc:
        logger.warning("macOS osascript 通知失败: %s", exc)


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def show_pre_operation_countdown(
    action: str,
    detail: str = "",
    seconds: int = DEFAULT_COUNTDOWN_SECONDS,
    tool_name: str = "computer",
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> Literal["proceed", "skip", "cancel"]:
    """操作前倒计时通知（阻塞）。

    在屏幕顶部显示一个系统最顶层的倒计时通知条。
    用户可以点击"跳过"立即执行，或"取消"中止操作。
    倒计时结束后自动关闭，返回 "proceed"。

    Args:
        action: 操作名称（如 click、type_text）
        detail: 操作详情（如坐标、目标文本）
        seconds: 倒计时秒数，默认 3
        event_callback: 可选事件回调（向前端推送倒计时状态）

    Returns:
        "proceed" — 倒计时结束，继续执行
        "skip"   — 用户点击跳过
        "cancel" — 用户点击取消
    """
    logger.info("[倒计时] %d秒后执行: %s (%s)", seconds, action, detail or "-")

    # 发送初始倒计时事件
    if event_callback:
        try:
            event_callback({
                "type": "countdown_start",
                "tool": tool_name,
                "action": action,
                "detail": detail,
                "seconds": seconds,
            })
        except Exception:
            pass

    try:
        root, result_code = _build_countdown_window(
            action, detail, seconds, tool_name, event_callback,
        )
        root.mainloop()

        exit_code = result_code[0]
        if exit_code == 1:
            logger.info("[倒计时] 用户跳过，立即执行")
            return "skip"
        elif exit_code == 2:
            logger.info("[倒计时] 用户取消操作")
            return "cancel"
        else:
            logger.info("[倒计时] 倒计时结束，开始执行")
            return "proceed"

    except Exception as exc:
        logger.warning("Tkinter 倒计时窗口失败，尝试 fallback: %s", exc)

        # macOS fallback: osascript
        if _IS_MACOS:
            try:
                return _macos_countdown_osascript(action, detail, seconds)  # type: ignore[return-value]
            except Exception as exc2:
                logger.warning("macOS osascript fallback 也失败: %s", exc2)

        # 最终 fallback：纯文本倒计时（无窗口）
        logger.info("[倒计时] 使用纯文本倒计时 fallback")
        for remaining in range(seconds, 0, -1):
            if event_callback:
                try:
                    event_callback({
                        "type": "countdown",
                        "tool": tool_name,
                        "action": action,
                        "remaining_seconds": remaining,
                    })
                except Exception:
                    pass
            time.sleep(1)
        return "proceed"


def show_post_operation_notification(
    action: str,
    detail: str = "",
    success: bool = True,
    seconds: int = DEFAULT_NOTIFY_SECONDS,
    tool_name: str = "computer",
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """操作后提示通知（非阻塞）。

    在屏幕底部显示一个系统最顶层的提示条，自动消失。
    在后台线程中运行，不阻塞调用者。

    Args:
        action: 操作名称
        detail: 操作详情
        success: 是否成功
        seconds: 自动关闭秒数，默认 2
        event_callback: 可选事件回调
    """
    # 发送完成事件
    if event_callback:
        try:
            event_callback({
                "type": "operation_done",
                "tool": tool_name,
                "action": action,
                "detail": detail,
                "ok": success,
            })
        except Exception:
            pass

    def _run() -> None:
        try:
            root = _build_notification_window(action, detail, success, seconds)
            root.mainloop()
        except Exception as exc:
            logger.warning("Tkinter 通知窗口失败: %s", exc)
            # macOS fallback
            if _IS_MACOS:
                _macos_notify_osascript(action, detail, success)

    t = threading.Thread(target=_run, daemon=True, name="countdown-notify")
    t.start()


# ---------------------------------------------------------------------------
# 独立测试入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("=== 测试操作前倒计时 ===")
    result = show_pre_operation_countdown(
        action="click",
        detail="x=120, y=340",
        seconds=3,
    )
    print(f"结果: {result}")

    print("\n=== 测试操作后通知（成功） ===")
    show_post_operation_notification(
        action="click",
        detail="x=120, y=340",
        success=True,
    )
    time.sleep(3)

    print("\n=== 测试操作后通知（失败） ===")
    show_post_operation_notification(
        action="type_text",
        detail="Hello World",
        success=False,
    )
    time.sleep(3)

    print("\n=== 完成 ===")
