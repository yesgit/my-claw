try:
    from backend.tools.knowledge.tool import KnowledgeTool
except ImportError:
    KnowledgeTool = None  # type: ignore[assignment,misc]

__all__ = ["KnowledgeTool"]
