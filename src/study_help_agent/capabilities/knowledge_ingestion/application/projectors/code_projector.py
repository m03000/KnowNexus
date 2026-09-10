"""把完整项目代码解析 Artifact 拆成项目报告和原子代码块知识资产。"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Mapping

from study_help_agent.runtime.artifacts.store import StoredArtifact
from study_help_agent.runtime.serialization import to_serializable

from ...domain.enums import KnowledgeAssetType, KnowledgeSpace
from ...domain.models import KnowledgeAssetDraft


class CodeAnalysisProjector:
    """避免索引查询副本，只投影最终 code_analysis_project 产物。"""

    artifact_type = "code_analysis_project"

    def project(self, artifact: StoredArtifact) -> tuple[KnowledgeAssetDraft, ...]:
        """创建一个项目报告资产，并为每个已解释代码块创建原子资产。"""

        payload = to_serializable(artifact.content)
        if not isinstance(payload, Mapping):
            raise TypeError("code_analysis_project content must be an object")
        project = payload.get("project")
        if not isinstance(project, Mapping):
            raise ValueError("code_analysis_project is missing project data")

        project_name = str(project.get("project_name") or artifact.name).strip()
        fingerprint = str(project.get("fingerprint") or artifact.artifact_id)
        files = project.get("files") or []
        if not isinstance(files, list):
            raise TypeError("project.files must be a list")

        root_id = self._tree_id(fingerprint, "project")
        assets: list[KnowledgeAssetDraft] = [
            self._project_report(
                artifact=artifact,
                project=project,
                project_name=project_name,
                fingerprint=fingerprint,
                files=files,
                run_metadata=payload.get("metadata"),
                root_id=root_id,
            )
        ]
        assets.extend(self._module_summaries(
            project_name=project_name,
            fingerprint=fingerprint,
            root_id=root_id,
            files=files,
        ))
        for source_file in files:
            if not isinstance(source_file, Mapping):
                continue
            assets.append(self._file_summary(
                project_name=project_name,
                fingerprint=fingerprint,
                root_id=root_id,
                source_file=source_file,
            ))
            for block in source_file.get("blocks") or []:
                if isinstance(block, Mapping):
                    assets.append(
                        self._code_block(
                            artifact=artifact,
                            project_name=project_name,
                            fingerprint=fingerprint,
                            source_file=source_file,
                            block=block,
                        )
                    )
        return tuple(assets)

    @staticmethod
    def _project_report(
        *,
        artifact: StoredArtifact,
        project: Mapping[str, Any],
        project_name: str,
        fingerprint: str,
        files: list[Any],
        run_metadata: Any,
        root_id: str,
    ) -> KnowledgeAssetDraft:
        """将项目摘要、结构和文件职责组织成可检索的 Markdown 报告。"""

        lines = [f"# {project_name} 项目解析报告", ""]
        summary = str(project.get("project_summary") or "").strip()
        if summary:
            lines.extend(["## 项目概述", "", summary, ""])
        lines.extend(["## 文件结构与职责", ""])
        for source_file in files:
            if not isinstance(source_file, Mapping):
                continue
            relative_path = str(source_file.get("relative_path") or "unknown")
            role = str(source_file.get("file_role") or "暂无职责说明")
            lines.append(f"### `{relative_path}`")
            lines.extend(["", role, ""])
        return KnowledgeAssetDraft(
            space=KnowledgeSpace.PROJECT_CODE,
            asset_type=KnowledgeAssetType.PROJECT_REPORT,
            stable_source_key=f"project:{fingerprint}:report",
            title=f"{project_name} 项目解析报告",
            content="\n".join(lines).strip(),
            metadata={
                "artifact_id": artifact.artifact_id,
                "project_name": project_name,
                "project_path": project.get("project_path", ""),
                "project_fingerprint": fingerprint,
                "total_files": len(files),
                "run_metadata": run_metadata or {},
                "tree_node_id": root_id,
                "tree_parent_id": "",
                "tree_node_type": "project",
                "tree_depth": 0,
                "tree_summary": summary or f"{project_name} 项目代码结构与职责总览",
            },
        )

    @classmethod
    def _module_summaries(
        cls,
        *,
        project_name: str,
        fingerprint: str,
        root_id: str,
        files: list[Any],
    ) -> tuple[KnowledgeAssetDraft, ...]:
        """从文件职责确定性聚合每一级目录摘要，不增加 LLM Token。"""

        module_files: dict[str, list[tuple[str, str]]] = {}
        child_modules: dict[str, set[str]] = {}
        for source_file in files:
            if not isinstance(source_file, Mapping):
                continue
            relative_path = cls._relative_path(source_file)
            parent = PurePosixPath(relative_path).parent.as_posix()
            if parent == ".":
                parent = ""
            role = str(source_file.get("file_role") or "暂无职责说明").strip()
            current = parent
            while current:
                module_files.setdefault(current, []).append((relative_path, role))
                parent_path = PurePosixPath(current).parent.as_posix()
                if parent_path == ".":
                    parent_path = ""
                if parent_path:
                    child_modules.setdefault(parent_path, set()).add(current)
                current = parent_path

        assets: list[KnowledgeAssetDraft] = []
        for module_path in sorted(module_files, key=lambda value: (value.count("/"), value)):
            entries = module_files[module_path]
            direct_children = sorted(child_modules.get(module_path, ()))
            lines = [
                f"# {module_path} 模块",
                "",
                f"- 所属项目：{project_name}",
                f"- 模块路径：`{module_path}`",
                f"- 覆盖文件：{len(entries)} 个",
            ]
            if direct_children:
                lines.extend(("", "## 子模块", ""))
                lines.extend(f"- `{path}`" for path in direct_children)
            lines.extend(("", "## 文件职责", ""))
            lines.extend(f"- `{path}`：{role}" for path, role in entries)
            node_id = cls._tree_id(fingerprint, "module", module_path)
            parent_path = PurePosixPath(module_path).parent.as_posix()
            if parent_path == ".":
                parent_path = ""
            parent_id = (
                cls._tree_id(fingerprint, "module", parent_path)
                if parent_path else root_id
            )
            assets.append(KnowledgeAssetDraft(
                space=KnowledgeSpace.PROJECT_CODE,
                asset_type=KnowledgeAssetType.MODULE_ANALYSIS,
                stable_source_key=f"project:{fingerprint}:tree:module:{module_path}",
                title=f"{project_name} / {module_path}",
                content="\n".join(lines),
                metadata={
                    "project_name": project_name,
                    "project_fingerprint": fingerprint,
                    "module_path": module_path,
                    "tree_node_id": node_id,
                    "tree_parent_id": parent_id,
                    "tree_node_type": "module",
                    "tree_depth": module_path.count("/") + 1,
                    "tree_summary": cls._module_summary(module_path, entries),
                },
            ))
        return tuple(assets)

    @classmethod
    def _file_summary(
        cls,
        *,
        project_name: str,
        fingerprint: str,
        root_id: str,
        source_file: Mapping[str, Any],
    ) -> KnowledgeAssetDraft:
        """把文件职责和符号目录保存为树的文件节点。"""

        relative_path = cls._relative_path(source_file)
        role = str(source_file.get("file_role") or "暂无职责说明").strip()
        blocks = [item for item in source_file.get("blocks") or [] if isinstance(item, Mapping)]
        lines = [
            f"# {PurePosixPath(relative_path).name}",
            "",
            f"- 所属项目：{project_name}",
            f"- 文件路径：`{relative_path}`",
            f"- 文件职责：{role}",
            "",
            "## 主要符号",
            "",
        ]
        lines.extend(
            f"- {item.get('code_type') or 'block'} `{item.get('code_name') or 'anonymous'}`："
            f"{str(item.get('explanation') or '').strip()[:240]}"
            for item in blocks
        )
        if not blocks:
            lines.append("- 无已解析符号")
        parent_path = PurePosixPath(relative_path).parent.as_posix()
        if parent_path == ".":
            parent_path = ""
        parent_id = (
            cls._tree_id(fingerprint, "module", parent_path)
            if parent_path else root_id
        )
        node_id = cls._tree_id(fingerprint, "file", relative_path)
        return KnowledgeAssetDraft(
            space=KnowledgeSpace.PROJECT_CODE,
            asset_type=KnowledgeAssetType.FILE_ANALYSIS,
            stable_source_key=f"project:{fingerprint}:tree:file:{relative_path}",
            title=f"{project_name} / {relative_path}",
            content="\n".join(lines),
            metadata={
                "project_name": project_name,
                "project_fingerprint": fingerprint,
                "file_path": relative_path,
                "tree_node_id": node_id,
                "tree_parent_id": parent_id,
                "tree_node_type": "file",
                "tree_depth": (parent_path.count("/") + 2) if parent_path else 1,
                "tree_summary": role,
            },
        )

    @staticmethod
    def _code_block(
        *,
        artifact: StoredArtifact,
        project_name: str,
        fingerprint: str,
        source_file: Mapping[str, Any],
        block: Mapping[str, Any],
    ) -> KnowledgeAssetDraft:
        """把源代码和对应解释保持在同一资产中，避免检索语义断裂。"""

        relative_path = str(source_file.get("relative_path") or "unknown")
        code_name = str(block.get("code_name") or "anonymous")
        code_type = str(block.get("code_type") or "block")
        line_start = int(block.get("line_start") or 1)
        line_end = int(block.get("line_end") or line_start)
        language = relative_path.rsplit(".", 1)[-1] if "." in relative_path else "text"
        content = (
            f"# {code_name}\n\n"
            f"- 项目：{project_name}\n"
            f"- 文件：`{relative_path}`\n"
            f"- 类型：{code_type}\n"
            f"- 行号：{line_start}-{line_end}\n\n"
            f"## 代码\n\n```{language}\n{str(block.get('full_code') or '').rstrip()}\n```\n\n"
            f"## 解析\n\n{str(block.get('explanation') or '').strip()}"
        )
        logical_key = f"{relative_path}:{code_type}:{code_name}:{line_start}"
        return KnowledgeAssetDraft(
            space=KnowledgeSpace.PROJECT_CODE,
            asset_type=KnowledgeAssetType.CODE_BLOCK_ANALYSIS,
            stable_source_key=f"project:{fingerprint}:block:{logical_key}",
            title=f"{relative_path} - {code_name}",
            content=content,
            metadata={
                "artifact_id": artifact.artifact_id,
                "project_name": project_name,
                "project_fingerprint": fingerprint,
                "file_path": relative_path,
                "language": language,
                "symbol_name": code_name,
                "symbol_type": code_type,
                "parent_class": block.get("parent_class", ""),
                "line_start": line_start,
                "line_end": line_end,
                "tree_node_id": CodeAnalysisProjector._tree_id(
                    fingerprint, "block", logical_key,
                ),
                "tree_parent_id": CodeAnalysisProjector._tree_id(
                    fingerprint, "file", relative_path,
                ),
                "tree_node_type": "block",
                "tree_depth": relative_path.count("/") + 2,
                "tree_summary": str(block.get("explanation") or "").strip()[:500],
            },
        )

    @staticmethod
    def _relative_path(source_file: Mapping[str, Any]) -> str:
        return str(source_file.get("relative_path") or "unknown").replace("\\", "/")

    @staticmethod
    def _tree_id(fingerprint: str, node_type: str, key: str = "") -> str:
        suffix = f":{key}" if key else ""
        return f"project-tree:{fingerprint}:{node_type}{suffix}"

    @staticmethod
    def _module_summary(module_path: str, entries: list[tuple[str, str]]) -> str:
        roles = "；".join(role for _, role in entries[:6])
        suffix = f"；另有 {len(entries) - 6} 个文件" if len(entries) > 6 else ""
        return f"{module_path} 模块：{roles}{suffix}"
