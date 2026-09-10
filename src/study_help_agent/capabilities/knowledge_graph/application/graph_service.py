"""三域图谱查询服务：各域独立加载，项目图支持局部展开。"""
from __future__ import annotations

from collections.abc import Callable

from .models import MemoryGraphQuery


def _empty_graph() -> dict:
    """未实现的图谱返回空结构占位，保持前端渲染契约稳定。"""
    return {"nodes": [], "edges": []}


class GraphQueryService:
    """聚合三个图谱；未实现的域返回空占位，前端按 node_type 区分渲染。"""

    def __init__(
        self,
        *,
        note_graph_provider: Callable[[], dict] | None = None,
        memory_graph_provider: Callable[[MemoryGraphQuery], dict] | None = None,
        memory_trace_provider: Callable[[str], dict] | None = None,
        memory_candidates_provider: Callable[[str, int], list[dict]] | None = None,
        memory_turn_provider: Callable[[str], dict] | None = None,
        memory_session_rename_provider: Callable[[str, str], bool] | None = None,
        memory_session_delete_provider: Callable[[str], dict[str, int] | None] | None = None,
        memory_turn_delete_provider: Callable[[str], dict[str, int] | None] | None = None,
        project_graph_provider: Callable[[int | None, bool], dict] | None = None,
        project_children_provider: Callable[[int, str], dict] | None = None,
    ) -> None:
        self._note_graph_provider = note_graph_provider
        self._memory_graph_provider = memory_graph_provider
        self._memory_trace_provider = memory_trace_provider
        self._memory_candidates_provider = memory_candidates_provider
        self._memory_turn_provider = memory_turn_provider
        self._memory_session_rename_provider = memory_session_rename_provider
        self._memory_session_delete_provider = memory_session_delete_provider
        self._memory_turn_delete_provider = memory_turn_delete_provider
        self._project_graph_provider = project_graph_provider
        self._project_children_provider = project_children_provider

    def get_note_graph(self) -> dict:
        """只返回笔记图谱。"""

        graph = self._note_graph_provider() if self._note_graph_provider else None
        return graph or _empty_graph()

    def get_memory_graph(self, query: MemoryGraphQuery | None = None) -> dict:
        """只返回记忆图谱，并保留语义过滤参数。"""

        graph = (
            self._memory_graph_provider(query or MemoryGraphQuery())
            if self._memory_graph_provider else None
        )
        return graph or _empty_graph()

    def rename_memory_session(self, session_id: str, title: str) -> bool:
        if self._memory_session_rename_provider is None:
            return False
        return self._memory_session_rename_provider(session_id, title)

    def delete_memory_session(self, session_id: str) -> dict[str, int] | None:
        if self._memory_session_delete_provider is None:
            return None
        return self._memory_session_delete_provider(session_id)

    def delete_memory_turn(self, turn_id: str) -> dict[str, int] | None:
        if self._memory_turn_delete_provider is None:
            return None
        return self._memory_turn_delete_provider(turn_id)

    def get_project_graph(
        self, *, project_id: int | None = None, include_blocks: bool = False,
    ) -> dict:
        """返回项目结构图；默认不加载代码块节点。"""

        graph = (
            self._project_graph_provider(project_id, include_blocks)
            if self._project_graph_provider else None
        )
        return graph or _empty_graph()

    def get_project_children(self, *, project_id: int, node_id: str) -> dict:
        """按父节点返回直接子节点，用于前端懒加载。"""

        if self._project_children_provider is None:
            return _empty_graph()
        return self._project_children_provider(project_id, node_id) or _empty_graph()

    def get_all_graphs(
            self,
            *,
            memory_query: MemoryGraphQuery | None = None,
    ) -> dict:
        """一次返回三个图谱。后续 memory/project 实现后，在这里追加 provider 即可。"""
        return {
            "note_graph": self.get_note_graph(),
            "memory_graph": self.get_memory_graph(memory_query),
            "project_graph": self.get_project_graph(include_blocks=False),
        }


    def trace_memory(self, memory_id: str) -> dict:
        """记忆溯源：记忆点 → 来源消息原话 → 来源会话聚类时间线。"""

        if self._memory_trace_provider is None:
            return {"memory": None, "messages": [], "sessions": []}
        return self._memory_trace_provider(memory_id)

    def get_memory_candidates(self, memory_id: str, limit: int = 5) -> list[dict]:
        """返回排除当前记忆与显式一跳关系后的语义近邻。"""

        if self._memory_candidates_provider is None:
            return []
        return self._memory_candidates_provider(memory_id, min(max(limit, 1), 10))

    def get_memory_turn(self, turn_id: str) -> dict:
        """读取记忆星点对应的一次完整原始提问与回答。"""

        if self._memory_turn_provider is None:
            return {"turn_id": turn_id, "found": False}
        return self._memory_turn_provider(turn_id)
