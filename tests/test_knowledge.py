"""知识库存储层和工具层单元测试。"""
from __future__ import annotations

import pytest

from backend.memory.embedding import MockEmbedding, cosine_similarity, _embed_to_bytes, _bytes_to_embed
from backend.memory.knowledge_store import KnowledgeStore
from backend.models import OperationRequest
from backend.tools.knowledge.tool import KnowledgeTool

import numpy as np


# ==================== Embedding 测试 ====================


class TestMockEmbedding:
    def test_dimension(self):
        emb = MockEmbedding(dimension=64)
        assert emb.dimension == 64

    def test_embed_returns_list(self):
        emb = MockEmbedding(dimension=32)
        vec = emb.embed("hello")
        assert isinstance(vec, list)
        assert len(vec) == 32

    def test_embed_deterministic(self):
        emb = MockEmbedding(dimension=32)
        v1 = emb.embed("test")
        v2 = emb.embed("test")
        assert v1 == v2

    def test_embed_batch(self):
        emb = MockEmbedding(dimension=16)
        results = emb.embed_batch(["a", "b", "c"])
        assert len(results) == 3
        assert all(len(v) == 16 for v in results)

    def test_embed_normalized(self):
        emb = MockEmbedding(dimension=32)
        vec = np.array(emb.embed("test"))
        norm = np.linalg.norm(vec)
        assert abs(norm - 1.0) < 1e-5


class TestCosineSimilarity:
    def test_identical_vectors(self):
        a = np.array([1.0, 0.0, 0.0])
        assert cosine_similarity(a, a) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_zero_vector(self):
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 0.0])
        assert cosine_similarity(a, b) == 0.0


class TestEmbedSerialization:
    def test_roundtrip(self):
        original = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        blob = _embed_to_bytes(original)
        restored = _bytes_to_embed(blob, 3)
        np.testing.assert_array_almost_equal(original, restored)


# ==================== KnowledgeStore 测试 ====================


class TestKnowledgeStore:
    @pytest.fixture
    def store(self):
        return KnowledgeStore(db_path=":memory:", embedding_provider=MockEmbedding(dimension=32))

    def test_add_and_get_document(self, store):
        doc_id = store.add_document(title="测试文档", content="这是测试内容。")
        doc = store.get_document(doc_id)
        assert doc is not None
        assert doc["title"] == "测试文档"
        assert doc["content"] == "这是测试内容。"
        assert doc["source_type"] == "text"
        assert doc["char_count"] == 7

    def test_get_nonexistent_document(self, store):
        assert store.get_document("nonexistent") is None

    def test_list_documents(self, store):
        store.add_document(title="文档1", content="内容1")
        store.add_document(title="文档2", content="内容2")
        docs = store.list_documents()
        assert len(docs) == 2
        titles = {d["title"] for d in docs}
        assert titles == {"文档1", "文档2"}

    def test_delete_document(self, store):
        doc_id = store.add_document(title="待删除", content="内容")
        assert store.delete_document(doc_id) is True
        assert store.get_document(doc_id) is None

    def test_delete_nonexistent(self, store):
        assert store.delete_document("nonexistent") is False

    def test_count_documents(self, store):
        assert store.count_documents() == 0
        store.add_document(title="A", content="a")
        store.add_document(title="B", content="b")
        assert store.count_documents() == 2

    def test_add_document_with_tags(self, store):
        doc_id = store.add_document(title="标签测试", content="内容", tags=["tag1", "tag2"])
        doc = store.get_document(doc_id)
        assert doc["tags"] == ["tag1", "tag2"]

    def test_list_documents_has_chunk_count(self, store):
        # 短文档只有一个 chunk
        doc_id = store.add_document(title="短文档", content="短内容")
        docs = store.list_documents()
        assert any(d["chunk_count"] >= 1 for d in docs)


class TestKnowledgeStoreUpdate:
    """update_document() 单元测试。"""

    @pytest.fixture
    def store(self):
        return KnowledgeStore(db_path=":memory:", embedding_provider=MockEmbedding(dimension=32))

    def test_update_title(self, store):
        doc_id = store.add_document(title="原标题", content="内容不变")
        updated = store.update_document(doc_id, title="新标题")
        assert updated is not None
        assert updated["title"] == "新标题"
        assert updated["content"] == "内容不变"

    def test_update_content(self, store):
        doc_id = store.add_document(title="测试", content="旧内容")
        updated = store.update_document(doc_id, content="新内容在这里")
        assert updated is not None
        assert updated["content"] == "新内容在这里"
        assert updated["char_count"] == len("新内容在这里")

    def test_update_tags(self, store):
        doc_id = store.add_document(title="测试", content="内容", tags=["a"])
        updated = store.update_document(doc_id, tags=["b", "c"])
        assert updated is not None
        assert updated["tags"] == ["b", "c"]

    def test_update_multiple_fields(self, store):
        doc_id = store.add_document(title="旧标题", content="旧内容", tags=["old"])
        updated = store.update_document(doc_id, title="新标题", content="新内容", tags=["new"])
        assert updated["title"] == "新标题"
        assert updated["content"] == "新内容"
        assert updated["tags"] == ["new"]

    def test_update_nonexistent_returns_none(self, store):
        result = store.update_document("nonexistent_id", title="不存在")
        assert result is None

    def test_update_content_rechunks(self, store):
        """内容变更后应重新分段。"""
        store_long = KnowledgeStore(
            db_path=":memory:",
            embedding_provider=MockEmbedding(dimension=16),
            chunk_size=50,
            chunk_overlap=10,
        )
        doc_id = store_long.add_document(title="长文", content="短")
        docs = store_long.list_documents()
        doc = next(d for d in docs if d["id"] == doc_id)
        assert doc["chunk_count"] == 1

        # 更新为长文本
        long_text = "这是一段很长的文本内容。" * 30
        store_long.update_document(doc_id, content=long_text)
        docs = store_long.list_documents()
        doc = next(d for d in docs if d["id"] == doc_id)
        assert doc["chunk_count"] > 1

    def test_update_content_searchable(self, store):
        """更新内容后新内容应可被搜索到。"""
        doc_id = store.add_document(title="文档", content="旧内容关于 Python 编程")
        # 更新为 Rust 相关内容
        store.update_document(doc_id, content="Rust 是一种系统级编程语言，注重安全性。")
        results = store.search("Rust 语言")
        assert len(results) > 0
        matched = [r for r in results if r["document_id"] == doc_id]
        assert len(matched) > 0
        assert "Rust" in matched[0]["content"]

    def test_update_no_changes_same_data(self, store):
        """传入相同数据应仍返回文档（updated_at 会刷新）。"""
        doc_id = store.add_document(title="不变", content="内容")
        updated = store.update_document(doc_id, title="不变")
        assert updated is not None
        assert updated["title"] == "不变"

    def test_update_only_title_preserves_chunks(self, store):
        """仅修改标题不应重建 chunks。"""
        store_chunk = KnowledgeStore(
            db_path=":memory:",
            embedding_provider=MockEmbedding(dimension=16),
            chunk_size=50,
            chunk_overlap=10,
        )
        long_text = "这是第一段内容。" * 20
        doc_id = store_chunk.add_document(title="原标题", content=long_text, tags=["t1"])
        docs_before = store_chunk.list_documents()
        chunks_before = next(d for d in docs_before if d["id"] == doc_id)["chunk_count"]

        store_chunk.update_document(doc_id, title="新标题")
        docs_after = store_chunk.list_documents()
        doc_after = next(d for d in docs_after if d["id"] == doc_id)
        assert doc_after["chunk_count"] == chunks_before
        assert doc_after["title"] == "新标题"


class TestKnowledgeStoreChunking:
    @pytest.fixture
    def store(self):
        return KnowledgeStore(
            db_path=":memory:",
            embedding_provider=MockEmbedding(dimension=16),
            chunk_size=50,
            chunk_overlap=10,
        )

    def test_short_text_single_chunk(self, store):
        doc_id = store.add_document(title="短文本", content="这是一段短文本。")
        docs = store.list_documents()
        doc = next(d for d in docs if d["id"] == doc_id)
        assert doc["chunk_count"] == 1

    def test_long_text_multiple_chunks(self, store):
        long_text = "这是第一段内容。" * 20 + "\n" + "这是第二段内容。" * 20
        doc_id = store.add_document(title="长文本", content=long_text)
        docs = store.list_documents()
        doc = next(d for d in docs if d["id"] == doc_id)
        assert doc["chunk_count"] > 1


class TestKnowledgeStoreSearch:
    @pytest.fixture
    def store(self):
        store = KnowledgeStore(
            db_path=":memory:",
            embedding_provider=MockEmbedding(dimension=32),
        )
        store.add_document(
            title="Python 编程",
            content="Python 是一种高级编程语言，广泛用于 Web 开发、数据分析和人工智能领域。",
        )
        store.add_document(
            title="JavaScript 指南",
            content="JavaScript 是 Web 前端的核心语言，也可以用于后端开发（Node.js）。",
        )
        store.add_document(
            title="Rust 语言",
            content="Rust 是一种系统级编程语言，注重安全性和性能，适合底层开发。",
        )
        return store

    def test_search_returns_results(self, store):
        results = store.search("Python 编程语言")
        assert len(results) > 0
        assert all("content" in r for r in results)
        assert all("score" in r for r in results)
        assert all("doc_title" in r for r in results)

    def test_search_top_k(self, store):
        results = store.search("编程语言", top_k=2)
        assert len(results) <= 2

    def test_search_result_has_snippet(self, store):
        results = store.search("Python")
        assert len(results) > 0
        assert "snippet" in results[0]


class TestKnowledgeStoreRebuild:
    def test_rebuild_all_fts(self):
        store = KnowledgeStore(db_path=":memory:", embedding_provider=MockEmbedding(dimension=16))
        store.add_document(title="测试", content="重建索引测试内容")
        count = store.rebuild_all_fts()
        assert count >= 1

    def test_regenerate_embeddings(self):
        store = KnowledgeStore(db_path=":memory:", embedding_provider=MockEmbedding(dimension=16))
        store.add_document(title="测试", content="重新嵌入测试内容")
        count = store.regenerate_embeddings()
        assert count >= 1


# ==================== KnowledgeTool 测试 ====================


class TestKnowledgeTool:
    @pytest.fixture
    def tool(self):
        store = KnowledgeStore(db_path=":memory:", embedding_provider=MockEmbedding(dimension=16))
        return KnowledgeTool(store=store)

    def test_describe(self, tool):
        desc = tool.describe()
        assert desc["tool"] == "knowledge"
        assert "search" in desc["supported_actions"]
        assert "add_text" in desc["supported_actions"]

    def test_execute_search(self, tool):
        # 先添加文档
        op = OperationRequest(
            tool="knowledge",
            action="add_text",
            resource="add_text",
            params={"title": "测试文档", "content": "Python 编程语言入门教程"},
            risk="medium",
        )
        tool.execute(op)

        # 搜索
        search_op = OperationRequest(
            tool="knowledge",
            action="search",
            resource="search",
            params={"query": "Python"},
            risk="low",
        )
        result = tool.execute(search_op)
        assert result["ok"] is True
        assert result["total"] >= 1

    def test_execute_add_text(self, tool):
        op = OperationRequest(
            tool="knowledge",
            action="add_text",
            resource="add_text",
            params={"title": "新文档", "content": "文档内容"},
            risk="medium",
        )
        result = tool.execute(op)
        assert result["ok"] is True
        assert "document_id" in result
        assert result["title"] == "新文档"

    def test_execute_add_text_missing_title(self, tool):
        op = OperationRequest(
            tool="knowledge",
            action="add_text",
            resource="add_text",
            params={"content": "没有标题"},
            risk="medium",
        )
        with pytest.raises(ValueError, match="title"):
            tool.execute(op)

    def test_execute_add_text_missing_content(self, tool):
        op = OperationRequest(
            tool="knowledge",
            action="add_text",
            resource="add_text",
            params={"title": "没有内容"},
            risk="medium",
        )
        with pytest.raises(ValueError, match="content"):
            tool.execute(op)

    def test_execute_list_docs(self, tool):
        # 添加两个文档
        for i in range(3):
            op = OperationRequest(
                tool="knowledge",
                action="add_text",
                resource="add_text",
                params={"title": f"文档{i}", "content": f"内容{i}"},
                risk="medium",
            )
            tool.execute(op)

        list_op = OperationRequest(
            tool="knowledge",
            action="list_docs",
            resource="list_docs",
            params={"limit": 2},
            risk="low",
        )
        result = tool.execute(list_op)
        assert result["ok"] is True
        assert len(result["documents"]) == 2
        assert result["total"] == 3

    def test_execute_get_doc(self, tool):
        add_op = OperationRequest(
            tool="knowledge",
            action="add_text",
            resource="add_text",
            params={"title": "获取测试", "content": "获取内容"},
            risk="medium",
        )
        add_result = tool.execute(add_op)
        doc_id = add_result["document_id"]

        get_op = OperationRequest(
            tool="knowledge",
            action="get_doc",
            resource=doc_id,
            params={},
            risk="low",
        )
        result = tool.execute(get_op)
        assert result["ok"] is True
        assert result["document"]["title"] == "获取测试"

    def test_execute_get_doc_not_found(self, tool):
        op = OperationRequest(
            tool="knowledge",
            action="get_doc",
            resource="nonexistent",
            params={},
            risk="low",
        )
        with pytest.raises(FileNotFoundError):
            tool.execute(op)

    def test_execute_delete_doc(self, tool):
        add_op = OperationRequest(
            tool="knowledge",
            action="add_text",
            resource="add_text",
            params={"title": "删除测试", "content": "删除内容"},
            risk="medium",
        )
        add_result = tool.execute(add_op)
        doc_id = add_result["document_id"]

        del_op = OperationRequest(
            tool="knowledge",
            action="delete_doc",
            resource=doc_id,
            params={},
            risk="high",
        )
        result = tool.execute(del_op)
        assert result["ok"] is True
        assert result["deleted_document_id"] == doc_id

    def test_execute_delete_doc_not_found(self, tool):
        op = OperationRequest(
            tool="knowledge",
            action="delete_doc",
            resource="nonexistent",
            params={},
            risk="high",
        )
        with pytest.raises(FileNotFoundError):
            tool.execute(op)

    def test_execute_unsupported_action(self, tool):
        op = OperationRequest(
            tool="knowledge",
            action="unsupported",
            resource="test",
            params={},
            risk="low",
        )
        with pytest.raises(ValueError, match="不支持"):
            tool.execute(op)

    def test_search_empty_query(self, tool):
        op = OperationRequest(
            tool="knowledge",
            action="search",
            resource="search",
            params={"query": ""},
            risk="low",
        )
        with pytest.raises(ValueError, match="query"):
            tool.execute(op)