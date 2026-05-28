from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from backend.memory.embedding import (
    EmbeddingProvider,
    MockEmbedding,
    _embed_to_bytes,
    _bytes_to_embed,
    cosine_similarity,
)

logger = logging.getLogger(__name__)

# 默认 chunk 配置
DEFAULT_CHUNK_SIZE = 500  # 字符数
DEFAULT_CHUNK_OVERLAP = 50
DEFAULT_SEARCH_TOP_K = 5
DEFAULT_HYBRID_ALPHA = 0.5  # BM25 和向量搜索的融合权重


class KnowledgeStore:
    """知识库存储层。

    功能：
    - 文档 CRUD
    - 自动分段（chunking）
    - FTS5 全文索引
    - 向量嵌入存储和余弦相似度搜索
    - 混合搜索（BM25 + 向量加权融合）
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> None:
        if db_path == ":memory:":
            self._db_path = ":memory:"
            self._memory_conn: sqlite3.Connection | None = None
        else:
            default_path = Path.home() / ".myclaw" / "knowledge.db"
            self._db_path = Path(db_path) if db_path else default_path
            if isinstance(self._db_path, Path):
                self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._memory_conn = None

        self._embedding = embedding_provider or MockEmbedding()
        if chunk_overlap >= chunk_size:
            raise ValueError(f"chunk_overlap ({chunk_overlap}) 必须 < chunk_size ({chunk_size})，否则分段会无限循环")
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._db_path == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:")
                self._memory_conn.execute("PRAGMA foreign_keys = ON")
            return self._memory_conn
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            # 文档表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'text',
                    source_name TEXT,
                    content TEXT NOT NULL,
                    char_count INTEGER NOT NULL DEFAULT 0,
                    tags TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            # Chunk 表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL DEFAULT 0,
                    content TEXT NOT NULL,
                    embedding BLOB,
                    char_start INTEGER NOT NULL DEFAULT 0,
                    char_end INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document_id
                ON knowledge_chunks (document_id)
                """
            )

            # FTS5 全文索引（独立表，chunk_id UNINDEXED 用于关联 knowledge_chunks）
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(
                        chunk_id UNINDEXED,
                        content,
                        tokenize='unicode61'
                    )
                    """
                )
            except sqlite3.OperationalError:
                # FTS5 表已存在
                pass

            conn.commit()

    # ==================== 文档管理 ====================

    def add_document(
        self,
        title: str,
        content: str,
        source_type: str = "text",
        source_name: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """添加文档，自动分段并生成嵌入向量。返回文档 ID。"""
        doc_id = str(uuid4())
        now = datetime.now().isoformat(timespec="seconds")
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        char_count = len(content)

        # 先分段和生成嵌入，再写入数据库，保证原子性
        chunks = self._split_text(content)
        chunk_data = self._prepare_chunk_data(chunks)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_documents (id, title, source_type, source_name, content, char_count, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (doc_id, title, source_type, source_name, content, char_count, tags_json, now, now),
            )

            for idx, (chunk, embedding_blob) in enumerate(chunk_data):
                chunk_id = str(uuid4())
                conn.execute(
                    """
                    INSERT INTO knowledge_chunks (id, document_id, chunk_index, content, embedding, char_start, char_end)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (chunk_id, doc_id, idx, chunk["content"], embedding_blob, chunk["char_start"], chunk["char_end"]),
                )

            conn.commit()
            # 更新 FTS 索引（同一事务后）
            self._rebuild_fts_for_document(conn, doc_id)

        return doc_id

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """获取文档详情。"""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, source_type, source_name, content, char_count, tags, created_at, updated_at
                FROM knowledge_documents WHERE id = ?
                """,
                (doc_id,),
            ).fetchone()

        if row is None:
            return None

        return {
            "id": row[0],
            "title": row[1],
            "source_type": row[2],
            "source_name": row[3],
            "content": row[4],
            "char_count": row[5],
            "tags": json.loads(row[6]),
            "created_at": row[7],
            "updated_at": row[8],
        }

    def list_documents(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        """列出所有文档（不含正文，节省带宽）。单条 SQL 查询包含 chunk_count。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT d.id, d.title, d.source_type, d.source_name, d.char_count,
                       d.tags, d.created_at, d.updated_at,
                       COALESCE(c.cnt, 0) as chunk_count
                FROM knowledge_documents d
                LEFT JOIN (
                    SELECT document_id, COUNT(*) as cnt
                    FROM knowledge_chunks
                    GROUP BY document_id
                ) c ON d.id = c.document_id
                ORDER BY d.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

            return [
                {
                    "id": row[0],
                    "title": row[1],
                    "source_type": row[2],
                    "source_name": row[3],
                    "char_count": row[4],
                    "tags": json.loads(row[5]),
                    "chunk_count": row[8],
                    "created_at": row[6],
                    "updated_at": row[7],
                }
                for row in rows
            ]

    def delete_document(self, doc_id: str) -> bool:
        """删除文档及其所有 chunk。"""
        with self._connect() as conn:
            # 先删除关联的 FTS 记录
            chunk_ids = conn.execute(
                "SELECT id FROM knowledge_chunks WHERE document_id = ?",
                (doc_id,),
            ).fetchall()
            for (chunk_id,) in chunk_ids:
                try:
                    conn.execute("DELETE FROM knowledge_chunks_fts WHERE chunk_id = ?", (chunk_id,))
                except Exception:
                    pass

            cursor = conn.execute(
                "DELETE FROM knowledge_documents WHERE id = ?",
                (doc_id,),
            )
            conn.execute(
                "DELETE FROM knowledge_chunks WHERE document_id = ?",
                (doc_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def count_documents(self) -> int:
        """返回文档总数。"""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM knowledge_documents").fetchone()
        return row[0] if row else 0

    # ==================== 分段 ====================

    def _split_text(self, text: str) -> list[dict[str, Any]]:
        """将文本按固定长度分段，带重叠。

        返回: [{"content": str, "char_start": int, "char_end": int}, ...]
        """
        if not text.strip():
            return []

        chunks: list[dict[str, Any]] = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + self._chunk_size, text_len)
            chunk_text = text[start:end]

            # 尝试在段落/句子边界处分段
            if end < text_len:
                # 优先找换行符
                last_newline = chunk_text.rfind("\n")
                if last_newline > self._chunk_size // 2:
                    end = start + last_newline + 1
                    chunk_text = text[start:end]
                else:
                    # 其次找句号等
                    for sep in ("。", "！", "？", ".", "!", "?", "；", ";"):
                        last_sep = chunk_text.rfind(sep)
                        if last_sep > self._chunk_size // 2:
                            end = start + last_sep + len(sep)
                            chunk_text = text[start:end]
                            break

            chunks.append({
                "content": chunk_text,
                "char_start": start,
                "char_end": end,
            })
            start = end - self._chunk_overlap if end < text_len else end

        return chunks

    def _prepare_chunk_data(self, chunks: list[dict[str, Any]]) -> list[tuple[dict[str, Any], bytes | None]]:
        """为 chunks 生成嵌入向量，返回 (chunk, embedding_blob) 列表。"""
        if not chunks:
            return []

        texts = [c["content"] for c in chunks]
        try:
            embeddings = self._embedding.embed_batch(texts)
        except Exception as exc:
            logger.warning("嵌入向量生成失败，将存储不带向量的 chunk: %s", exc)
            embeddings = [None] * len(texts)

        result = []
        for chunk, embedding in zip(chunks, embeddings):
            try:
                embedding_blob = _embed_to_bytes(np.array(embedding, dtype=np.float32)) if embedding else None
            except (ValueError, TypeError) as exc:
                logger.debug("嵌入向量序列化失败: %s", exc)
                embedding_blob = None
            result.append((chunk, embedding_blob))
        return result

    def _rebuild_fts_for_document(self, conn: sqlite3.Connection, doc_id: str) -> None:
        """重建单个文档的 FTS 索引。"""
        # 一次查询获取 id + content，同时用于删除旧 FTS 和插入新 FTS
        chunk_rows = conn.execute(
            "SELECT id, content FROM knowledge_chunks WHERE document_id = ?",
            (doc_id,),
        ).fetchall()

        for chunk_id, _content in chunk_rows:
            try:
                conn.execute("DELETE FROM knowledge_chunks_fts WHERE chunk_id = ?", (chunk_id,))
            except Exception as exc:
                logger.debug("删除 FTS 记录失败 (chunk %s): %s", chunk_id, exc)

        for chunk_id, content in chunk_rows:
            try:
                conn.execute(
                    "INSERT INTO knowledge_chunks_fts (chunk_id, content) VALUES (?, ?)",
                    (chunk_id, content),
                )
            except Exception as exc:
                logger.debug("插入 FTS 记录失败 (chunk %s): %s", chunk_id, exc)
        conn.commit()

    def rebuild_all_fts(self) -> int:
        """重建所有 FTS 索引。返回重建的 chunk 数。"""
        with self._connect() as conn:
            try:
                conn.execute("DELETE FROM knowledge_chunks_fts")
            except Exception:
                pass

            rows = conn.execute(
                "SELECT id, content FROM knowledge_chunks"
            ).fetchall()

            fts_count = 0
            for chunk_id, content in rows:
                try:
                    conn.execute(
                        "INSERT INTO knowledge_chunks_fts (chunk_id, content) VALUES (?, ?)",
                        (chunk_id, content),
                    )
                    fts_count += 1
                except Exception as exc:
                    logger.debug("插入 FTS 记录失败 (chunk %s): %s", chunk_id, exc)
            conn.commit()
        return fts_count

    # ==================== 搜索 ====================

    def search(
        self,
        query: str,
        top_k: int = DEFAULT_SEARCH_TOP_K,
        alpha: float = DEFAULT_HYBRID_ALPHA,
    ) -> list[dict[str, Any]]:
        """混合搜索：BM25 关键词搜索 + 向量余弦相似度搜索，加权融合。

        Args:
            query: 查询文本
            top_k: 返回最多 top_k 个结果
            alpha: BM25 权重 (0~1)，1-alpha 为向量权重

        Returns:
            [{"chunk_id", "document_id", "chunk_index", "content", "snippet",
              "score", "source_type", "doc_title"}, ...]
        """
        bm25_results = self._search_bm25(query, top_k=top_k * 3)
        vector_results = self._search_vector(query, top_k=top_k * 3)

        # 合并结果：RRF 风格的加权融合
        merged = self._merge_results(bm25_results, vector_results, alpha)

        # 取 top_k，并补充文档信息
        results = merged[:top_k]
        return self._enrich_results(results)

    def _search_bm25(self, query: str, top_k: int = 15) -> list[dict[str, Any]]:
        """FTS5 BM25 关键词搜索。"""
        with self._connect() as conn:
            try:
                fts_rows = conn.execute(
                    """
                    SELECT chunk_id, bm25(knowledge_chunks_fts) as score
                    FROM knowledge_chunks_fts
                    WHERE knowledge_chunks_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (query, top_k),
                ).fetchall()
            except (sqlite3.OperationalError, sqlite3.DatabaseError):
                return []

            if not fts_rows:
                return []

            fts_chunk_ids = [r[0] for r in fts_rows]
            placeholders = ",".join("?" * len(fts_chunk_ids))
            chunk_rows = conn.execute(
                f"""
                SELECT id, document_id, chunk_index, content
                FROM knowledge_chunks WHERE id IN ({placeholders})
                """,
                fts_chunk_ids,
            ).fetchall()

            chunk_map = {r[0]: r for r in chunk_rows}

            results = []
            for chunk_id, score in fts_rows:
                chunk = chunk_map.get(chunk_id)
                if chunk is None:
                    continue
                results.append({
                    "chunk_id": chunk[0],
                    "document_id": chunk[1],
                    "chunk_index": chunk[2],
                    "content": chunk[3],
                    "bm25_score": -score,
                })
            return results

    def _search_vector(self, query: str, top_k: int = 15) -> list[dict[str, Any]]:
        """向量余弦相似度搜索。"""
        try:
            query_embedding = self._embedding.embed(query)
        except Exception as exc:
            logger.warning("查询嵌入生成失败: %s", exc)
            return []

        query_vec = np.array(query_embedding, dtype=np.float32)

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, document_id, chunk_index, content, embedding
                FROM knowledge_chunks
                WHERE embedding IS NOT NULL
                """
            ).fetchall()

        results = []
        for row in rows:
            chunk_id, doc_id, chunk_idx, content, embedding_blob = row
            if not embedding_blob:
                continue
            try:
                chunk_vec = _bytes_to_embed(embedding_blob, query_vec.shape[0])
            except ValueError as exc:
                logger.debug("跳过维度不匹配的 chunk %s: %s", chunk_id, exc)
                continue
            sim = cosine_similarity(query_vec, chunk_vec)
            results.append({
                "chunk_id": chunk_id,
                "document_id": doc_id,
                "chunk_index": chunk_idx,
                "content": content,
                "vector_score": sim,
            })

        # 按相似度降序排列
        results.sort(key=lambda x: x["vector_score"], reverse=True)
        return results[:top_k]

    def _merge_results(
        self,
        bm25_results: list[dict[str, Any]],
        vector_results: list[dict[str, Any]],
        alpha: float,
    ) -> list[dict[str, Any]]:
        """合并 BM25 和向量搜索结果，加权融合。"""
        # 归一化分数
        bm25_scores = [r["bm25_score"] for r in bm25_results]
        vector_scores = [r["vector_score"] for r in vector_results]

        max_bm25 = max(bm25_scores) if bm25_scores else 1.0
        max_vector = max(vector_scores) if vector_scores else 1.0
        if max_bm25 == 0:
            max_bm25 = 1.0
        if max_vector == 0:
            max_vector = 1.0

        # 以 chunk_id 为 key 合并
        merged_map: dict[str, dict[str, Any]] = {}

        for r in bm25_results:
            cid = r["chunk_id"]
            merged_map[cid] = {
                **r,
                "norm_bm25": r["bm25_score"] / max_bm25,
                "norm_vector": 0.0,
            }

        for r in vector_results:
            cid = r["chunk_id"]
            if cid in merged_map:
                merged_map[cid]["norm_vector"] = r["vector_score"] / max_vector
            else:
                merged_map[cid] = {
                    **r,
                    "norm_bm25": 0.0,
                    "norm_vector": r["vector_score"] / max_vector,
                }

        # 计算融合分数
        for item in merged_map.values():
            item["score"] = alpha * item["norm_bm25"] + (1 - alpha) * item["norm_vector"]

        # 排序
        sorted_results = sorted(merged_map.values(), key=lambda x: x["score"], reverse=True)
        return sorted_results

    def _enrich_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """为搜索结果补充文档元信息。"""
        if not results:
            return []

        # 批量获取文档信息（单条 SQL）
        doc_ids = list({r["document_id"] for r in results})
        doc_map: dict[str, dict[str, Any]] = {}

        with self._connect() as conn:
            placeholders = ",".join("?" * len(doc_ids))
            rows = conn.execute(
                f"""
                SELECT id, title, source_type, source_name
                FROM knowledge_documents WHERE id IN ({placeholders})
                """,
                doc_ids,
            ).fetchall()
            for row in rows:
                doc_map[row[0]] = {
                    "title": row[1],
                    "source_type": row[2],
                    "source_name": row[3],
                }

        enriched = []
        for r in results:
            doc_info = doc_map.get(r["document_id"], {})
            snippet = r["content"][:200] + ("..." if len(r["content"]) > 200 else "")
            enriched.append({
                "chunk_id": r["chunk_id"],
                "document_id": r["document_id"],
                "chunk_index": r["chunk_index"],
                "content": r["content"],
                "snippet": snippet,
                "score": round(r.get("score", 0.0), 4),
                "doc_title": doc_info.get("title", ""),
                "source_type": doc_info.get("source_type", ""),
                "source_name": doc_info.get("source_name", ""),
            })

        return enriched

    # ==================== 重建索引 ====================

    def regenerate_embeddings(self) -> int:
        """重新生成所有 chunk 的嵌入向量（如更换了嵌入模型后使用）。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, content FROM knowledge_chunks"
            ).fetchall()

        if not rows:
            return 0

        texts = [r[1] for r in rows]
        chunk_ids = [r[0] for r in rows]

        # 分批嵌入（每批最多 20 条）
        batch_size = 20
        all_embeddings: list[list[float] | None] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                batch_embeddings = self._embedding.embed_batch(batch)
                all_embeddings.extend(batch_embeddings)
            except Exception as exc:
                logger.warning("批量嵌入失败 (batch %d): %s", i, exc)
                all_embeddings.extend([None] * len(batch))

        success_count = 0
        with self._connect() as conn:
            for chunk_id, embedding in zip(chunk_ids, all_embeddings):
                if embedding is not None:
                    embedding_blob = _embed_to_bytes(np.array(embedding, dtype=np.float32))
                    success_count += 1
                    conn.execute(
                        "UPDATE knowledge_chunks SET embedding = ? WHERE id = ?",
                        (embedding_blob, chunk_id),
                    )
                # embedding 为 None 时保留旧向量，不清除
            conn.commit()

        return success_count
