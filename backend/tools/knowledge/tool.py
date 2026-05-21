from __future__ import annotations

from backend.memory.knowledge_store import KnowledgeStore
from backend.models import OperationRequest


class KnowledgeTool:
    """知识库工具，支持搜索、添加、查看、列出、删除文档。"""

    tool_name = "knowledge"
    description = "知识库工具，支持搜索、添加文本、查看、列出和删除知识文档"
    supported_actions = {
        "search": "low",
        "add_text": "medium",
        "list_docs": "low",
        "get_doc": "low",
        "delete_doc": "high",
    }

    def __init__(self, store: KnowledgeStore | None = None) -> None:
        self._store = store or KnowledgeStore()

    def describe(self) -> dict:
        """返回工具的标准自描述信息。"""
        actions = [
            {"name": action, "default_risk": risk}
            for action, risk in self.supported_actions.items()
        ]
        return {
            "tool": self.tool_name,
            "type": "local",
            "actions": actions,
            "input_schema": {},
            "description": self.description,
            "supported_actions": dict(self.supported_actions),
        }

    def execute(self, operation: OperationRequest) -> dict:
        if operation.action == "search":
            return self._search(operation)
        if operation.action == "add_text":
            return self._add_text(operation)
        if operation.action == "list_docs":
            return self._list_docs(operation)
        if operation.action == "get_doc":
            return self._get_doc(operation)
        if operation.action == "delete_doc":
            return self._delete_doc(operation)

        raise ValueError(f"不支持的 action: {operation.action}")

    def _search(self, operation: OperationRequest) -> dict:
        query = operation.params.get("query")
        if not query or not isinstance(query, str) or not query.strip():
            raise ValueError("search 需要 params.query（非空字符串）")
        top_k = operation.params.get("top_k", 5)
        if not isinstance(top_k, int) or top_k < 1:
            top_k = 5
        top_k = min(top_k, 20)

        results = self._store.search(query=query.strip(), top_k=top_k)
        return {
            "ok": True,
            "tool": self.tool_name,
            "action": operation.action,
            "query": query.strip(),
            "results": results,
            "total": len(results),
        }

    def _add_text(self, operation: OperationRequest) -> dict:
        title = operation.params.get("title")
        content = operation.params.get("content")
        if not title or not isinstance(title, str) or not title.strip():
            raise ValueError("add_text 需要 params.title（非空字符串）")
        if not content or not isinstance(content, str) or not content.strip():
            raise ValueError("add_text 需要 params.content（非空字符串）")

        tags = operation.params.get("tags")
        if tags is not None and not isinstance(tags, list):
            raise ValueError("params.tags 必须是字符串数组")

        doc_id = self._store.add_document(
            title=title.strip(),
            content=content.strip(),
            source_type="text",
            tags=tags,
        )
        doc = self._store.get_document(doc_id)
        return {
            "ok": True,
            "tool": self.tool_name,
            "action": operation.action,
            "document_id": doc_id,
            "title": title.strip(),
            "char_count": doc["char_count"] if doc else len(content),
        }

    def _list_docs(self, operation: OperationRequest) -> dict:
        limit = operation.params.get("limit", 20)
        offset = operation.params.get("offset", 0)
        if not isinstance(limit, int) or limit < 1:
            limit = 20
        if not isinstance(offset, int) or offset < 0:
            offset = 0

        docs = self._store.list_documents(limit=limit, offset=offset)
        total = self._store.count_documents()
        return {
            "ok": True,
            "tool": self.tool_name,
            "action": operation.action,
            "documents": docs,
            "total": total,
        }

    def _get_doc(self, operation: OperationRequest) -> dict:
        doc_id = operation.resource
        if not doc_id or not doc_id.strip():
            raise ValueError("get_doc 的 resource 必须是文档 ID")

        doc = self._store.get_document(doc_id.strip())
        if doc is None:
            raise FileNotFoundError(f"文档不存在: {doc_id}")

        return {
            "ok": True,
            "tool": self.tool_name,
            "action": operation.action,
            "document": doc,
        }

    def _delete_doc(self, operation: OperationRequest) -> dict:
        doc_id = operation.resource
        if not doc_id or not doc_id.strip():
            raise ValueError("delete_doc 的 resource 必须是文档 ID")

        deleted = self._store.delete_document(doc_id.strip())
        if not deleted:
            raise FileNotFoundError(f"文档不存在: {doc_id}")

        return {
            "ok": True,
            "tool": self.tool_name,
            "action": operation.action,
            "deleted_document_id": doc_id.strip(),
        }