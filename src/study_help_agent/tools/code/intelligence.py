"""Code Sub-Agent 对外使用的三个高层工具。

项目分析与单文件分析各自调用同一套内部条件图；查询工具统一访问已保存结果。
Agent不再直接编排扫描、AST、文件职责、代码块解释和装配步骤。
底层完整结果进入 Artifact Store，Observation 只返回覆盖率和稳定引用。
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from study_help_agent.capabilities.code_analysis.application.service import (
    CodeAnalysisService,
)
from study_help_agent.capabilities.code_analysis.mini_agents import (
    CodeAnalysisMiniAgent,
)
from study_help_agent.runtime.tools import ToolDefinition, ToolExecutionContext, ToolResult
from study_help_agent.capabilities.code_analysis.domain.models import ExplanationProjectStatus

logger = logging.getLogger(__name__)


class CodeIntelligenceTools:
    """把完整代码分析用例注册为少量、语义明确的 Agent 工具。"""

    def __init__(
        self,
        *,
        mini_agent: CodeAnalysisMiniAgent,
        service: CodeAnalysisService,
    ) -> None:
        """注入分析图、只读应用服务和结果持久化端口。"""

        self._mini_agent = mini_agent
        self._service = service

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """返回项目、多文件、单文件分析与有界增量补齐工具。"""

        common = {
            "project_path": {
                "type": "string",
                "description": "允许访问的本地 Python 项目绝对目录。",
            },
            "analysis_goal": {
                "type": "string",
                "description": "希望重点理解的业务、模块、调用链或技术问题。",
            },
        }
        return (
            ToolDefinition(
                name="analyze_local_code_project",
                description=(
                    "完整分析一个本地 Python 项目。内部条件图会安全扫描、解析 AST 和项目内导入关系，"
                    "根据 analysis_goal 选择有限关键文件，按重要性过滤并批量解释代码块，生成项目架构报告；"
                    "源码与分析请求双指纹完全一致时复用缓存，"
                    "并对失败文件有界重试。适用于项目整体、模块关系或调用链理解；输入必须是本地项目目录。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        **common,
                        "max_files": {
                            "type": "integer",
                            "description": "本轮最多深度解析的关键文件数，范围 1 到 20。",
                            "minimum": 1,
                            "maximum": 20,
                        },
                    },
                    "required": ["project_path", "analysis_goal"],
                    "additionalProperties": False,
                },
                handler=self.analyze_project,
            ),
            ToolDefinition(
                name="analyze_local_code_files",
                description=(
                    "在同一个本地 Python 项目上下文中分析多个指定文件。内部共享扫描、导入关系和"
                    "项目摘要，并行分析文件职责与代码块；只对失败文件进行图内增量补齐。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        **common,
                        "target_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 20,
                            "description": "需要分析的项目相对路径列表。",
                        },
                    },
                    "required": ["project_path", "target_files", "analysis_goal"],
                    "additionalProperties": False,
                },
                handler=self.analyze_files,
            ),
            ToolDefinition(
                name="analyze_local_code_file",
                description=(
                    "在所属本地 Python 项目的导入和架构上下文中解析一个明确文件，生成"
                    "文件职责以及类、函数、方法和顶层语句组的代码块解释。 "
                    "内部会按重要性过滤、批量调用模型并优先复用精确缓存。"
                    "target_file必须是项目相对路径或能唯一匹配的路径后缀。"
                    "不要用于不存在于项目中的粘贴代码。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        **common,
                        "target_file": {
                            "type": "string",
                            "description": "目标 Python 文件的项目相对路径。",
                        },
                    },
                    "required": ["project_path", "target_file", "analysis_goal"],
                    "additionalProperties": False,
                },
                handler=self.analyze_file,
            ),
            ToolDefinition(
                name="complete_code_analysis",
                description=(
                    "仅当 analyze_local_code_project 返回 completion_status=partial 时调用。"
                    "读取原 code_analysis_project Artifact 中的 failed_paths，只重试缺失文件并"
                    "合并回原项目；禁止对已完成文件重跑。每个项目分析最多调用一次。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "analysis_artifact_id": {
                            "type": "string",
                            "description": "待补齐的 code_analysis_project Artifact ID。",
                        },
                        "analysis_goal": {
                            "type": "string",
                            "description": "原始代码分析目标。",
                        },
                    },
                    "required": ["analysis_artifact_id", "analysis_goal"],
                    "additionalProperties": False,
                },
                handler=self.complete_analysis,
            ),
        )

    def analyze_files(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """运行多文件模式，并复用与项目分析相同的发布链路。"""

        project_path = str(arguments["project_path"])
        target_files = [str(item) for item in arguments["target_files"]]
        analysis_goal = str(arguments["analysis_goal"])
        source_fp, analysis_fp = self._mini_agent.cache_identity(
            project_path=project_path,
            analysis_goal=analysis_goal,
            mode="files",
            max_files=len(target_files),
            target_files=target_files,
        )
        cached = self._service.find_cached_analysis(
            project_path=project_path,
            source_fingerprint=source_fp,
            analysis_fingerprint=analysis_fp,
        )
        if cached is not None:
            return self._publish(
                context=context, project=cached,
                metadata=self._cached_metadata(cached), cached=True,
            )
        project, metadata = self._mini_agent.analyze_files(
            project_path=project_path,
            target_files=target_files,
            analysis_goal=analysis_goal,
            cancellation_token=context.cancellation_token,
        )
        return self._publish(context=context, project=project, metadata=metadata)

    def analyze_project(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """运行项目分析图并按请求保存结果。"""

        max_files = int(arguments.get("max_files", 8))
        if not 1 <= max_files <= 20:
            raise ValueError("max_files 必须在 1 到 20 之间")
        project_path = str(arguments["project_path"])
        analysis_goal = str(arguments["analysis_goal"])
        source_fp, analysis_fp = self._mini_agent.cache_identity(
            project_path=project_path,
            analysis_goal=analysis_goal,
            mode="project",
            max_files=max_files,
        )
        cached = self._service.find_cached_analysis(
            project_path=project_path,
            source_fingerprint=source_fp,
            analysis_fingerprint=analysis_fp,
        )
        logger.info(
            "code_analysis_cache mode=project hit=%s source=%s analysis=%s goal=%r",
            cached is not None, source_fp[:12], analysis_fp[:12], analysis_goal[:120],
        )
        if cached is not None:
            return self._publish(
                context=context,
                project=cached,
                metadata=self._cached_metadata(cached),
                cached=True,
            )
        project, metadata = self._mini_agent.analyze_project(
            project_path=project_path,
            analysis_goal=analysis_goal,
            max_files=max_files,
            cancellation_token=context.cancellation_token,
        )
        return self._publish(
            context=context,
            project=project,
            metadata=metadata,
            allow_followup=True,
        )

    def complete_analysis(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """只重试原分析中的缺失文件，并将成功结果合并回原项目。"""

        artifact = context.artifact_store.get(str(arguments["analysis_artifact_id"]))
        if artifact.artifact_type != "code_analysis_project":
            raise ValueError("analysis_artifact_id 必须指向 code_analysis_project")
        content = artifact.content
        project = content["project"]
        original = dict(content["metadata"])
        failed_paths = [str(path) for path in original.get("failed_paths", [])]
        if not failed_paths:
            return self._publish(
                context=context, project=project, metadata=original,
                cached=True, resolves_followup=True,
            )
        repaired, repair_meta = self._mini_agent.analyze_files(
            project_path=project.project_path,
            target_files=failed_paths,
            analysis_goal=str(arguments["analysis_goal"]),
            cancellation_token=context.cancellation_token,
        )
        merged_by_path = {item.relative_path: item for item in project.files}
        merged_by_path.update({item.relative_path: item for item in repaired.files})
        project.files = list(merged_by_path.values())
        remaining = list(repair_meta.get("failed_paths", []))
        expected_files = int(original.get("expected_file_count", len(original.get("selected_paths", []))))
        expected_blocks = int(original.get("expected_block_count", project.total_blocks))
        completed_blocks = min(project.total_blocks, expected_blocks) if expected_blocks else project.total_blocks
        structure_coverage = (
            (expected_files - len(remaining)) / expected_files if expected_files else 1.0
        )
        block_coverage = (
            min(completed_blocks / expected_blocks, 1.0) if expected_blocks else structure_coverage
        )
        coverage = min(structure_coverage, block_coverage)
        completed = not remaining and coverage == 1.0
        project.status = (
            ExplanationProjectStatus.COMPLETED if completed else ExplanationProjectStatus.STALE
        )
        metadata = {
            **original,
            "failed_paths": remaining,
            "errors": list(original.get("errors", [])) + list(repair_meta.get("errors", [])),
            "coverage": coverage,
            "structure_coverage": structure_coverage,
            "block_coverage": block_coverage,
            "completed_block_count": completed_blocks,
            "completion_status": "completed" if completed else "partial",
        }
        return self._publish(
            context=context,
            project=project,
            metadata=metadata,
            resolves_followup=True,
        )

    def analyze_file(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """运行单文件模式图并按请求保存结果。"""

        project_path = str(arguments["project_path"])
        target_file = str(arguments["target_file"])
        analysis_goal = str(arguments["analysis_goal"])
        source_fp, analysis_fp = self._mini_agent.cache_identity(
            project_path=project_path,
            analysis_goal=analysis_goal,
            mode="file",
            max_files=1,
            target_file=target_file,
        )
        cached = self._service.find_cached_analysis(
            project_path=project_path,
            source_fingerprint=source_fp,
            analysis_fingerprint=analysis_fp,
        )
        logger.info(
            "code_analysis_cache mode=file hit=%s source=%s analysis=%s target=%s goal=%r",
            cached is not None, source_fp[:12], analysis_fp[:12], target_file,
            analysis_goal[:120],
        )
        if cached is not None:
            return self._publish(
                context=context,
                project=cached,
                metadata=self._cached_metadata(cached),
                cached=True,
            )
        project, metadata = self._mini_agent.analyze_file(
            project_path=project_path,
            target_file=target_file,
            analysis_goal=analysis_goal,
            cancellation_token=context.cancellation_token,
        )
        return self._publish(
            context=context,
            project=project,
            metadata=metadata,
        )

    def _publish(
        self,
        *,
        context: ToolExecutionContext,
        project,
        metadata: Mapping[str, Any],
        cached: bool = False,
        allow_followup: bool = False,
        resolves_followup: bool = False,
    ) -> ToolResult:
        """统一保存候选 Artifact，并可在图验收后持久化项目。"""

        completed = metadata["completion_status"] == "completed"
        outcome_label = "完成" if completed else "降级完成"
        failed_paths = list(metadata["failed_paths"])
        artifact = context.artifact_store.put(
            artifact_type="code_analysis_project",
            name=project.project_name,
            summary=(
                f"代码分析{outcome_label}：{project.total_files} 个文件、"
                f"{project.total_blocks} 个代码块，覆盖率 {metadata['coverage']:.0%}。"
                + (f" 未完成文件：{', '.join(failed_paths)}。" if failed_paths else "")
            ),
            content={"project": project, "metadata": dict(metadata)},
        )
        project_id = project.project_id if cached else self._service.publish(project)
        return ToolResult(
            summary=artifact.summary,
            payload={
                "project_id": project_id,
                "saved": True,
                "cached": cached,
                "project_summary": project.project_summary,
                "file_summaries": [
                    {
                        "path": source_file.relative_path,
                        "role": source_file.file_role,
                        "key_blocks": [
                            {
                                "name": block.code_name,
                                "type": block.code_type.value,
                                "summary": block.explanation[:240],
                            }
                            for block in source_file.blocks[:8]
                        ],
                        "remaining_blocks": max(0, len(source_file.blocks) - 8),
                    }
                    for source_file in project.files
                ],
                "coverage": metadata["coverage"],
                "total_files": project.total_files,
                "total_blocks": project.total_blocks,
                "analyzed_files": len(project.files),
                "failed_file_count": len(failed_paths),
                "structure_coverage": metadata.get("structure_coverage", metadata["coverage"]),
                "block_coverage": metadata.get("block_coverage", metadata["coverage"]),
                "completion_status": metadata["completion_status"],
                "terminal_outcome": "completed" if completed else "degraded",
                "selected_paths": list(metadata["selected_paths"]),
                "failed_paths": failed_paths,
                "requires_followup": bool(not completed and allow_followup),
                "resolves_followup": resolves_followup,
            },
            artifact_ids=(artifact.artifact_id,),
            warnings=tuple(metadata["errors"]),
            # 覆盖补齐属于内部条件图的职责。即使两轮后仍存在不可处理文件，
            # Artifact 也已经是本轮稳定终态，不能诱导外层 Agent 重跑整张图。
            partial=not completed,
        )

    @staticmethod
    def _cached_metadata(project) -> dict[str, Any]:
        """把完整缓存恢复成与新分析一致的工具观察元数据。"""

        paths = [item.relative_path for item in project.files]
        return {
            "coverage": 1.0,
            "completion_status": "completed",
            "selected_paths": paths,
            "failed_paths": [],
            "errors": [],
        }
