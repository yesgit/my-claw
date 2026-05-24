from __future__ import annotations

"""全局调试开关管理。

开启后，LLM 请求/响应内容、工具调用参数和返回结果等详细信息
会写入日志文件（~/.myclaw/myclaw.log）。
"""

import logging

_debug_logger = logging.getLogger("myclaw.debug")

# 内存态开关，重启后恢复默认（关闭）
_debug_enabled: bool = False


def is_debug_enabled() -> bool:
    """返回当前调试模式是否开启。"""
    return _debug_enabled


def set_debug_enabled(enabled: bool) -> bool:
    """设置调试模式开关，返回设置后的值。"""
    global _debug_enabled
    _debug_enabled = bool(enabled)
    _debug_logger.info("[debug] 调试模式已%s", "开启" if _debug_enabled else "关闭")
    return _debug_enabled