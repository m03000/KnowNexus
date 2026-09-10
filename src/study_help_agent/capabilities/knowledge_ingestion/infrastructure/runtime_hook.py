"""把通用 ToolResultObserver 协议适配到知识资产自动捕获用例。"""

from study_help_agent.capabilities.knowledge_ingestion.application.coordinator import (
    KnowledgeIngestionCoordinator,
)
from study_help_agent.capabilities.knowledge_ingestion.domain.policies import AutoIngestionPolicy
from study_help_agent.runtime.hooks.protocols import ToolResultObserverOutput
from study_help_agent.runtime.tools.core import ToolExecutionContext, ToolResult


class AutoIngestionHook:
    """筛选工具最终产物并返回待索引任务，故障由 ToolExecutor 隔离。"""

    def __init__(
        self,
        *,
        coordinator: KnowledgeIngestionCoordinator,
        policy: AutoIngestionPolicy | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._policy = policy or AutoIngestionPolicy()

    def after_success(
        self,
        *,
        tool_name: str,
        result: ToolResult,
        context: ToolExecutionContext,
    ) -> ToolResultObserverOutput:
        """仅捕获白名单中的完整 Artifact，并返回资产和任务引用。"""

        jobs: list[dict[str, object]] = []
        if context.cancellation_token is not None:
            context.cancellation_token.raise_if_cancelled()
        for artifact_id in result.artifact_ids:
            if context.cancellation_token is not None:
                context.cancellation_token.raise_if_cancelled()
            artifact = context.artifact_store.get(artifact_id)
            if not self._policy.accepts(
                artifact_type=artifact.artifact_type,
                partial=result.partial,
            ):
                continue
            for receipt in self._coordinator.capture(artifact):
                if context.cancellation_token is not None:
                    context.cancellation_token.raise_if_cancelled()
                jobs.append({
                    "artifact_id": artifact.artifact_id,
                    "asset_id": receipt.asset_id,
                    "job_id": receipt.job_id,
                    "created": receipt.created,
                    "skipped_reason": receipt.skipped_reason,
                })
        if not jobs:
            return ToolResultObserverOutput()
        return ToolResultObserverOutput(payload={
            "knowledge_ingestion": {
                "status": "pending" if any(item["created"] for item in jobs) else "unchanged",
                "items": jobs,
                "triggered_by": tool_name,
            }
        })
