"""代码领域的根到叶树索引检索。"""

from __future__ import annotations

from study_help_agent.capabilities.rag.domain.models import RetrievedChunk


class CodeTreeRetriever:
    """使用摘要向量逐层选择项目、模块、文件和代码块。

    每层保留少量候选形成 beam，避免单分支误判。查询向量只计算一次；
    返回叶子代码块时附带父节点摘要，供后续重排和回答阶段理解上下文。
    """

    def __init__(
        self,
        *,
        vector_store,
        code_service=None,
        fallback_retriever=None,
        beam_width: int = 3,
        max_depth: int = 12,
    ) -> None:
        if beam_width < 1:
            raise ValueError("beam_width 必须大于 0")
        if max_depth < 1:
            raise ValueError("max_depth 必须大于 0")
        self._vector_store = vector_store
        self._code_service = code_service
        self._fallback = fallback_retriever
        self._beam_width = beam_width
        self._max_depth = max_depth

    def retrieve(self, *, query: str, limit: int) -> list[RetrievedChunk]:
        if not query.strip() or limit < 1:
            return []
        active_fingerprints = self._active_fingerprints()
        if self._code_service is not None and not active_fingerprints:
            return []
        query_vector = self._vector_store.encode_query(query)
        roots = self._vector_store.retrieve_tree_nodes(
            query_vector=query_vector,
            roots=True,
            project_fingerprints=active_fingerprints,
            limit=max(self._beam_width, min(limit, 3)),
        )
        if not roots:
            return self._fallback_results(query=query, limit=limit)

        paths = {
            self._node_id(root): (self._context_line(root),)
            for root in roots
        }
        frontier = roots[: self._beam_width]
        deepest = frontier
        leaves: list[RetrievedChunk] = []

        for _ in range(self._max_depth):
            parent_ids = tuple(
                node_id for node in frontier
                if (node_id := self._node_id(node))
            )
            if not parent_ids:
                break
            children = self._vector_store.retrieve_tree_nodes(
                query_vector=query_vector,
                parent_ids=parent_ids,
                limit=max(limit * 3, self._beam_width * len(parent_ids)),
            )
            if not children:
                break

            next_frontier: list[RetrievedChunk] = []
            for child in children:
                node_id = self._node_id(child)
                parent_id = str(child.metadata.get("tree_parent_id") or "")
                paths[node_id] = (*paths.get(parent_id, ()), self._context_line(child))
                if str(child.metadata.get("tree_node_type")) == "block":
                    leaves.append(self._with_tree_context(child, paths[node_id]))
                else:
                    next_frontier.append(child)

            if leaves and (len(leaves) >= limit or not next_frontier):
                break
            if not next_frontier:
                break
            frontier = next_frontier[: self._beam_width]
            deepest = frontier

        if leaves:
            return leaves[:limit]
        return [
            self._with_tree_context(node, paths.get(self._node_id(node), ()))
            for node in deepest[:limit]
        ]

    def _active_fingerprints(self) -> tuple[str, ...]:
        """仅遍历每个项目当前可见版本，旧指纹子树不会参与召回。"""

        if self._code_service is None:
            return ()
        return tuple(
            str(project.fingerprint)
            for project in self._code_service.list_projects()
            if str(project.fingerprint).strip()
        )

    def _fallback_results(self, *, query: str, limit: int) -> list[RetrievedChunk]:
        """旧项目尚未重建树资产时保持可检索，重新分析后自动退出降级。"""

        if self._fallback is None:
            return []
        return self._fallback.retrieve(query=query, limit=limit)

    @staticmethod
    def _node_id(chunk: RetrievedChunk) -> str:
        return str(chunk.metadata.get("tree_node_id") or "")

    @staticmethod
    def _context_line(chunk: RetrievedChunk) -> str:
        node_type = str(chunk.metadata.get("tree_node_type") or "node")
        summary = str(chunk.metadata.get("tree_summary") or chunk.title).strip()
        return f"{node_type}: {summary}"

    @staticmethod
    def _with_tree_context(
        chunk: RetrievedChunk,
        path: tuple[str, ...],
    ) -> RetrievedChunk:
        context = "\n".join(f"- {item}" for item in path[:-1] if item)
        text = chunk.text
        if context:
            text = f"## 树索引父级上下文\n{context}\n\n{text}"
        metadata = dict(chunk.metadata)
        metadata["tree_path"] = list(path)
        return chunk.with_updates(
            text=text,
            metadata=metadata,
            retrieval_channels=("tree",),
        )
