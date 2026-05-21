from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _embed_to_bytes(vec: np.ndarray) -> bytes:
    """将 float32 numpy 数组序列化为二进制（小端）。"""
    return vec.astype(np.float32).tobytes()


def _bytes_to_embed(data: bytes, dim: int) -> np.ndarray:
    """从二进制反序列化为 float32 numpy 数组。"""
    vec = np.frombuffer(data, dtype=np.float32).copy()
    if vec.shape[0] != dim:
        raise ValueError(f"嵌入维度不匹配: 期望 {dim}，实际 {vec.shape[0]}")
    return vec


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """计算两个向量的余弦相似度。"""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


class EmbeddingProvider(ABC):
    """嵌入模型抽象基类。"""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """返回嵌入向量维度。"""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """将文本转换为嵌入向量。"""

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入，默认逐条调用。子类可覆写以支持批量 API。"""
        return [self.embed(t) for t in texts]


class OpenAICompatibleEmbedding(EmbeddingProvider):
    """通过 OpenAI 兼容 API 调用嵌入模型。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._dimension = dimension
        self._timeout = timeout

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        import httpx

        url = f"{self._base_url}/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        payload = {
            "model": self._model,
            "input": texts,
        }
        response = httpx.post(url, json=payload, headers=headers, timeout=self._timeout)
        if response.status_code != 200:
            raise RuntimeError(f"Embedding API 调用失败 (HTTP {response.status_code}): {response.text[:500]}")

        data = response.json()
        embeddings_data = data.get("data", [])
        if len(embeddings_data) != len(texts):
            raise RuntimeError(
                f"Embedding API 返回数量不匹配：期望 {len(texts)}，实际 {len(embeddings_data)}"
            )

        # 按 index 排序确保顺序正确
        embeddings_data.sort(key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in embeddings_data]


class MockEmbedding(EmbeddingProvider):
    """用于测试的模拟嵌入模型，返回确定性随机向量。"""

    def __init__(self, dimension: int = 64) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:
        rng = np.random.RandomState(hash(text) % (2**31))
        vec = rng.randn(self._dimension).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class EmbeddingConfig:
    """嵌入模型配置，持久化为 JSON。"""

    def __init__(
        self,
        provider: str = "openai_compatible",
        base_url: str = "",
        api_key: str = "",
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
        timeout: float = 30.0,
    ) -> None:
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.dimension = dimension
        self.timeout = timeout

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "baseUrl": self.base_url,
            "model": self.model,
            "dimension": self.dimension,
            "timeout": self.timeout,
            # api_key 不序列化到 JSON，单独管理
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], api_key: str = "") -> EmbeddingConfig:
        return cls(
            provider=data.get("provider", "openai_compatible"),
            base_url=data.get("baseUrl", ""),
            api_key=api_key,
            model=data.get("model", "text-embedding-3-small"),
            dimension=data.get("dimension", 1536),
            timeout=data.get("timeout", 30.0),
        )


def create_embedding_provider(config: EmbeddingConfig) -> EmbeddingProvider:
    """根据配置创建嵌入模型实例。"""
    if config.provider == "mock":
        return MockEmbedding(dimension=config.dimension)

    if not config.base_url:
        raise ValueError("嵌入模型 base_url 不能为空")
    if not config.api_key:
        raise ValueError("嵌入模型 api_key 不能为空")

    return OpenAICompatibleEmbedding(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        dimension=config.dimension,
        timeout=config.timeout,
    )


# ==================== 配置文件管理 ====================

_EMBEDDING_CONFIG_PATH = Path.home() / ".myclaw" / "embedding_config.json"
_EMBEDDING_API_KEY_PATH = Path.home() / ".myclaw" / "embedding_api_key"


def load_embedding_config() -> EmbeddingConfig:
    """从磁盘加载嵌入模型配置。"""
    config_path = _EMBEDDING_CONFIG_PATH
    if not config_path.exists():
        return EmbeddingConfig()

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return EmbeddingConfig()

    api_key = ""
    if _EMBEDDING_API_KEY_PATH.exists():
        try:
            api_key = _EMBEDDING_API_KEY_PATH.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    return EmbeddingConfig.from_dict(data, api_key=api_key)


def save_embedding_config(config: EmbeddingConfig) -> None:
    """保存嵌入模型配置到磁盘。api_key 单独存储。"""
    config_path = _EMBEDDING_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if config.api_key:
        key_path = _EMBEDDING_API_KEY_PATH
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(config.api_key, encoding="utf-8")
        # 限制 API Key 文件仅所有者可读
        try:
            import os
            import stat
            os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
