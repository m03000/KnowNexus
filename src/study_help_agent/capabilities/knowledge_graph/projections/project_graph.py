"""项目图谱适配器：投影项目包含树和 Python 文件间的导入关系。

包含关系来自已持久化的项目树；imports 关系基于已保存的源码快照重新执行确定性
AST 分析。它不读取用户当前磁盘，也不引入调用关系或额外 LLM 调用。

节点类型约定（前端按 node_type 渲染，无 payload 的节点纯展示）：
- project  项目：仅展示摘要
- module   模块目录：仅展示介绍
- file     文件：可查看 → GET /api/library/code-projects/{pid}/file?file_path=...
- block    代码块：可查看 → 同一接口 + start_line 定位
"""

from pathlib import Path, PurePosixPath

from study_help_agent.capabilities.code_analysis.application.service import (
    CodeAnalysisService,
)
from study_help_agent.capabilities.code_analysis.application.dto import (
    ExplainedFileContent,
)
from study_help_agent.capabilities.code_analysis.domain.source_analysis import (
    ImportGraphBuilder,
    PythonSourceAnalyzer,
)
from study_help_agent.capabilities.rag.infrastructure.qdrant_store import QdrantChunkStore


def build_project_graph(
    code_service: CodeAnalysisService,
    project_id: int | None = None,
    include_blocks: bool = True,
) -> dict:
    """返回项目图谱 nodes + edges（统一 {"nodes": [...], "edges": [...]} 格式）。"""
    nodes: list[dict] = []
    edges: list[dict] = []
    edge_index = 0

    def add_edge(source: str, target: str, label: str = "contains") -> None:
        nonlocal edge_index
        edge_index += 1
        edges.append(
            {
                "id": f"e{edge_index}",
                "source": source,
                "target": target,
                "label": label,
                "edge_type": label,
            }
        )

    summaries = code_service.list_projects()
    if project_id is not None:
        summaries = [item for item in summaries if item.project_id == project_id]
    for summary in summaries:
        project_id = summary.project_id
        project_node_id = f"project:{project_id}"
        nodes.append(
            {
                "id": project_node_id,
                "label": summary.project_name,
                "node_type": "project",
                "domain": "project",
                "summary": (
                    summary.project_summary
                    or (
                        f"{summary.project_path} · {summary.status.value} · "
                        f"{summary.total_files} 文件 / {summary.total_blocks} 代码块"
                    )
                ),
            }
        )

        project_tree = code_service.get_project_tree(project_id)
        module_ids: dict[str, str] = {}
        module_roles: dict[str, list[str]] = {}
        for folder in project_tree:
            for file in folder.files:
                current = folder.folder.strip("/")
                while current:
                    if file.file_role:
                        module_roles.setdefault(current, []).append(file.file_role)
                    parent = PurePosixPath(current).parent.as_posix()
                    current = "" if parent == "." else parent

        def ensure_module(module_path: str) -> str:
            """逐级创建目录节点，避免把 a/b/c 压成单个扁平模块。"""

            normalized = module_path.strip("/")
            if not normalized:
                return project_node_id
            if normalized in module_ids:
                return module_ids[normalized]
            parent_path = PurePosixPath(normalized).parent.as_posix()
            if parent_path == ".":
                parent_path = ""
            parent_id = ensure_module(parent_path)
            module_id = f"module:{project_id}:{normalized}"
            module_ids[normalized] = module_id
            nodes.append({
                "id": module_id,
                "label": PurePosixPath(normalized).name,
                "node_type": "module",
                "domain": "project",
                "summary": _module_display_summary(
                    normalized, module_roles.get(normalized, []),
                ),
                "payload": {"project_id": project_id, "module_path": normalized},
            })
            add_edge(parent_id, module_id)
            return module_id

        project_files = []
        file_node_ids: dict[str, str] = {}
        for folder in project_tree:
            parent_node_id = ensure_module(folder.folder)
            for file in folder.files:
                relative_path = file.relative_path or file.file_name
                file_node_id = f"file:{project_id}:{relative_path}"
                nodes.append(
                    {
                        "id": file_node_id,
                        "label": file.file_name,
                        "node_type": "file",
                        "domain": "project",
                        "summary": f"{file.file_path} · {file.file_role}",
                        "payload": {
                            "project_id": project_id,
                            "file_path": file.file_path,
                            "relative_path": relative_path,
                        },
                    }
                )
                project_files.append(file)
                file_node_ids[relative_path] = file_node_id
                add_edge(parent_node_id, file_node_id)

                for symbol in file.symbols if include_blocks else ():
                    block_node_id = (
                        f"block:{project_id}:{relative_path}:"
                        f"{symbol.name}:{symbol.start_line}"
                    )
                    nodes.append(
                        {
                            "id": block_node_id,
                            "label": symbol.name,
                            "node_type": symbol.symbol_type.value,
                            "domain": "project",
                            "summary": (
                                symbol.summary
                                or (
                                    f"{symbol.symbol_type.value} · "
                                    f"L{symbol.start_line}-{symbol.end_line} · "
                                    f"{file.file_path}"
                                )
                            ),
                            "payload": {
                                "project_id": project_id,
                                "file_path": file.file_path,
                                "start_line": symbol.start_line,
                                "end_line": symbol.end_line,
                                "symbol_type": symbol.symbol_type.value,
                                "parent_class": symbol.parent_class,
                            },
                        }
                    )
                    add_edge(file_node_id, block_node_id)

        for source_path, target_path in _project_imports(
            code_service, project_id, project_files,
        ):
            source_id = file_node_ids.get(source_path)
            target_id = file_node_ids.get(target_path)
            if source_id and target_id and source_id != target_id:
                add_edge(source_id, target_id, "imports")

    return {"nodes": nodes, "edges": edges}


def _module_display_summary(module_path: str, roles: list[str]) -> str:
    """给前端图谱提供与树索引一致的轻量模块摘要。"""

    unique_roles = list(dict.fromkeys(role.strip() for role in roles if role.strip()))
    if not unique_roles:
        return f"目录：{module_path}"
    visible = "；".join(unique_roles[:5])
    suffix = f"；另含 {len(unique_roles) - 5} 类职责" if len(unique_roles) > 5 else ""
    return f"{module_path}：{visible}{suffix}"


def build_project_graph_children(
    code_service: CodeAnalysisService,
    project_id: int,
    node_id: str,
) -> dict:
    """从完整单项目投影中裁剪出某节点的直接子图。"""

    graph = build_project_graph(
        code_service, project_id=project_id, include_blocks=True,
    )
    edges = [
        edge for edge in graph["edges"]
        if edge["source"] == node_id and edge["edge_type"] == "contains"
    ]
    child_ids = {edge["target"] for edge in edges}
    nodes = [node for node in graph["nodes"] if node["id"] in child_ids]
    return {"nodes": nodes, "edges": edges}


def _project_imports(
    code_service: CodeAnalysisService,
    project_id: int,
    project_files: list,
) -> tuple[tuple[str, str], ...]:
    """从数据库中的源码快照生成项目内部文件导入边。"""

    analyzer = PythonSourceAnalyzer()
    parsed_files = []
    for file in project_files:
        relative_path = (file.relative_path or file.file_name).replace("\\", "/")
        if not relative_path.casefold().endswith(".py"):
            continue
        try:
            content = code_service.get_file_content(
                project_id=project_id,
                file_path=file.file_path,
            )
            if not isinstance(content, ExplainedFileContent):
                continue
            parsed_files.append(analyzer.parse(
                absolute_path=Path(file.file_path),
                relative_path=relative_path,
                source_text="\n".join(content.source_lines),
            ))
        except (OSError, SyntaxError, UnicodeError, ValueError):
            # 单个历史源码快照不可解析时，保留包含树，不伪造导入边。
            continue

    if len(parsed_files) < 2:
        return ()
    graph = ImportGraphBuilder().build(parsed_files)
    return tuple(
        (source_path, target_path)
        for source_path, context in graph.by_file.items()
        for target_path in context.internal_imports
    )


def search_project_documents(
    *,
    code_service,
    vector_store: QdrantChunkStore,
    query: str,
    limit: int = 5,
) -> list[dict]:
    """项目图检索:树定位 → block → 反查向量库同一代码块文档。"""
    terms = tuple(term for term in query.casefold().split() if term)
    hits = []  # 命中的 block 节点
    for project in code_service.list_projects():
        tree = code_service.get_project_tree(project.project_id)
        for folder in tree:
            for file in folder.files:
                path = file.relative_path or file.file_path
                searchable = " ".join(
                    (
                        project.project_name,
                        folder.folder,
                        path,
                        file.file_role,
                        *(symbol.name for symbol in file.symbols),
                    )
                ).casefold()
                if terms and not any(term in searchable for term in terms):
                    continue
                for symbol in file.symbols:
                    hits.append((project, path, symbol))
    # 反查向量文档
    docs = []
    for project, path, symbol in hits[:limit]:
        chunks = vector_store.get_by_metadata(
            collection_key="project_code",
            metadata_filter={
                "file_path": path,
                "symbol_name": symbol.name,
                "line_start": symbol.start_line,
            },
            limit=1,
        )
        for chunk in chunks:
            docs.append({
                "node": {
                    "id": f"block:{project.project_id}:{path}:{symbol.name}:{symbol.start_line}",
                    "label": f"{path}:{symbol.name}",
                    "node_type": "block",
                    "domain": "project",
                },
                "chunk": chunk,
            })
    return docs


class ProjectStructureRetriever:
    """把项目包含树检索适配成统一的结构检索器接口。"""

    def __init__(
        self,
        *,
        code_service: CodeAnalysisService,
        vector_store: QdrantChunkStore,
    ) -> None:
        self._code_service = code_service
        self._vector_store = vector_store

    def retrieve(self, *, query: str, limit: int):
        return [
            item["chunk"]
            for item in search_project_documents(
                code_service=self._code_service,
                vector_store=self._vector_store,
                query=query,
                limit=limit,
            )
        ]

