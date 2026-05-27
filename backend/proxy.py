from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_PROXY_CONFIG_PATH = Path.home() / ".myclaw" / "proxy_config.json"


@dataclass(slots=True)
class ProxyConfig:
    """全局代理配置。"""

    enabled: bool = False
    url: str = ""
    no_proxy: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "url": self.url,
            "noProxy": self.no_proxy,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProxyConfig:
        return cls(
            enabled=bool(data.get("enabled", False)),
            url=str(data.get("url", "")).strip(),
            no_proxy=list(data.get("noProxy", [])),
        )


def load_proxy_config() -> ProxyConfig:
    """从磁盘加载全局代理配置。"""
    if not _PROXY_CONFIG_PATH.exists():
        return ProxyConfig()
    try:
        data = json.loads(_PROXY_CONFIG_PATH.read_text(encoding="utf-8"))
        return ProxyConfig.from_dict(data)
    except Exception:
        return ProxyConfig()


def save_proxy_config(config: ProxyConfig) -> None:
    """保存全局代理配置到磁盘。"""
    _PROXY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROXY_CONFIG_PATH.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _match_no_proxy(target_url: str, no_proxy_patterns: list[str]) -> bool:
    """检查目标 URL 是否匹配 noProxy 列表。

    支持精确域名匹配和通配符后缀匹配（如 *.local）。
    """
    try:
        parsed = urlparse(target_url)
        hostname = parsed.hostname or ""
    except Exception:
        hostname = target_url

    hostname = hostname.lower()

    for pattern in no_proxy_patterns:
        pattern = pattern.strip().lower()
        if not pattern:
            continue

        # 精确匹配
        if hostname == pattern:
            return True

        # 通配符后缀匹配：*.example.com → example.com
        if pattern.startswith("*."):
            suffix = pattern[2:]
            if hostname == suffix or hostname.endswith("." + suffix):
                return True

        # 简单后缀匹配：.example.com → 所有子域名
        if pattern.startswith("."):
            if hostname.endswith(pattern) or hostname == pattern[1:]:
                return True

        # 直接后缀匹配：example.com → sub.example.com 也匹配
        if hostname.endswith("." + pattern):
            return True

    return False


def resolve_effective_proxy(
    proxy_mode: str,
    proxy_url: str,
    target_url: str,
) -> str | None:
    """根据 proxy_mode 和全局配置，解析出实际生效的代理 URL。

    Args:
        proxy_mode: "global" | "custom" | "none"
        proxy_url: 当 proxy_mode == "custom" 时使用的代理地址
        target_url: 目标请求 URL（用于 noProxy 检查）

    Returns:
        有效的代理 URL 字符串，或 None 表示不使用代理。
    """
    if proxy_mode == "none":
        return None

    if proxy_mode == "custom":
        custom_url = proxy_url.strip()
        if not custom_url:
            return None
        return custom_url

    # proxy_mode == "global"
    global_config = load_proxy_config()
    if not global_config.enabled or not global_config.url.strip():
        return None

    if _match_no_proxy(target_url, global_config.no_proxy):
        logger.debug("[proxy] 目标 %s 命中 noProxy，跳过代理", target_url)
        return None

    return global_config.url.strip()