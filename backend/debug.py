from __future__ import annotations

"""全局调试开关管理。

开启后，LLM 请求/响应内容、工具调用参数和返回结果等详细信息
会写入日志文件（~/.myclaw/myclaw.log）。
"""

import logging
from pathlib import Path

_debug_logger = logging.getLogger("myclaw.debug")

# 内存态开关，重启后恢复默认（关闭）
_debug_enabled: bool = False

# ---- 日志文件配置 ----
_LOG_DIR = Path.home() / ".myclaw"
_LOG_FILE = _LOG_DIR / "myclaw.log"

# 记录各 logger 原始级别，关闭调试时恢复
_saved_levels: dict[str, int] = {}

# 需要控制级别的 logger
# - myclaw.* 系列：webapp 等显式命名的 logger
# - backend.* 系列：各模块使用 __name__ 注册的 logger
_MANAGED_LOGGERS = [
    "myclaw",
    "myclaw.debug",
    "myclaw.webapp",
    "backend",
    "backend.llm",
    "backend.agent",
    "backend.tool_router",
    "backend.mcp",
    "backend.memory",
    "backend.tools",
    "backend.policy_guard",
]

# 确保文件 handler 只添加一次
_file_handler_added: bool = False


def _ensure_file_handler() -> None:
    """确保日志文件 handler 已添加到 myclaw 和 backend 两个 logger 家族。"""
    global _file_handler_added
    if _file_handler_added:
        return

    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)

        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-5s [%(name)s] %(message)s", datefmt="%H:%M:%S"
        )
        file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8", mode="a")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)

        # 同时挂到 myclaw 和 backend 两棵 logger 树上
        for root_name in ("myclaw", "backend"):
            parent = logging.getLogger(root_name)
            # 避免重复添加
            already = any(
                isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == str(_LOG_FILE)
                for h in parent.handlers
            )
            if not already:
                parent.addHandler(file_handler)

        _file_handler_added = True
        _debug_logger.info("[debug] 日志文件已初始化: %s", _LOG_FILE)
    except Exception as exc:  # noqa: BLE001
        _debug_logger.warning("[debug] 无法创建日志文件: %s", exc)


def is_debug_enabled() -> bool:
    """返回当前调试模式是否开启。"""
    return _debug_enabled


def set_debug_enabled(enabled: bool) -> bool:
    """设置调试模式开关，返回设置后的值。"""
    global _debug_enabled
    _debug_enabled = bool(enabled)

    if _debug_enabled:
        _ensure_file_handler()
        # 保存原始级别并提升到 DEBUG
        for name in _MANAGED_LOGGERS:
            logger = logging.getLogger(name)
            if name not in _saved_levels:
                _saved_levels[name] = logger.level or logging.WARNING
            logger.setLevel(logging.DEBUG)
        _debug_logger.info("[debug] 调试模式已开启，详细日志写入 %s", _LOG_FILE)
    else:
        # 恢复原始级别
        for name in _MANAGED_LOGGERS:
            logger = logging.getLogger(name)
            saved = _saved_levels.pop(name, None)
            if saved is not None:
                logger.setLevel(saved)
        _debug_logger.info("[debug] 调试模式已关闭")

    return _debug_enabled