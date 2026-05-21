"""macOS 企业微信自动化实现。

使用 pyautogui（键鼠操作）+ pyobjc（窗口管理）+ Pillow（截图）。
"""
from __future__ import annotations

from backend.tools.wecom.macos.reader import MacWeComReader

__all__ = ["MacWeComReader"]