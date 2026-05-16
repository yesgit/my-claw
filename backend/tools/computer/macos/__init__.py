"""macOS 桌面自动化实现。

使用 pyautogui（键鼠操作）+ pyobjc（窗口管理、Accessibility）。
"""
from __future__ import annotations

from backend.tools.computer.macos.window_manager import MacWindowManager
from backend.tools.computer.macos.reader import MacControlReader
from backend.tools.computer.macos.actor import MacDesktopActor

__all__ = ["MacWindowManager", "MacControlReader", "MacDesktopActor"]
