"""Loop Agent 的程序化完成验收。

LLM 负责提出 Finish，Completion Policy 负责判断是否允许结束。这样既保留自主性，
又能避免文件未生成、关键工具未执行或回答为空时出现“假完成”。
"""

from dataclasses import dataclass
from typing import Protocol
from collections.abc import Mapping

from study_help_agent.runtime.artifacts import ArtifactStore
from study_help_agent.runtime.state import (
    AgentRunState,
    FinishAction,
    ObservationStatus,
)


@dataclass(frozen=True, slots=True)
class CompletionValidation:
    """保存完成验收是否通过以及可反馈给 Agent 的问题。"""

    accepted: bool
    issues: tuple[str, ...] = ()


class CompletionPolicy(Protocol):
    """定义不同任务可替换的完成验收接口。"""

    def validate(
        self,
        *,
        state: AgentRunState,
        action: FinishAction,
        artifact_store: ArtifactStore,
    ) -> CompletionValidation:
        """验证当前状态和 Finish 申请是否满足完成条件。"""
        ...


class DefaultCompletionPolicy:
    """提供最小成功动作和必需 Artifact 类型的通用验收。"""

    def __init__(
        self,
        *,
        minimum_successful_actions: int = 1,
        required_artifact_types: tuple[str, ...] = (),
        required_if_keywords: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        """配置通用完成标准，具体应用可以注入更严格策略。"""

        if minimum_successful_actions < 0:
            raise ValueError("minimum_successful_actions cannot be negative")
        self._minimum_successful_actions = minimum_successful_actions
        self._required_artifact_types = frozenset(required_artifact_types)
        self._required_if_keywords = {
            artifact_type: tuple(keywords)
            for artifact_type, keywords in (required_if_keywords or {}).items()
        }

    def validate(
        self,
        *,
        state: AgentRunState,
        action: FinishAction,
        artifact_store: ArtifactStore,
    ) -> CompletionValidation:
        """检查回答、成功观察数量以及必须存在的产物类型。"""

        issues: list[str] = []
        if not action.answer.strip():
            issues.append("Final answer cannot be empty")
        terminal_task = any(
            observation.payload.get("task_terminal") is True
            for observation in state.observations
        )
        # A terminal business failure still needs one LLM-written final response,
        # but it cannot satisfy success-only artifact requirements by definition.
        if terminal_task:
            return CompletionValidation(accepted=not issues, issues=tuple(issues))
        followup_pending = False
        for observation in state.observations:
            if observation.payload.get("requires_followup") is True:
                followup_pending = True
            if observation.payload.get("resolves_followup") is True:
                followup_pending = False
        if followup_pending:
            issues.append("A required bounded follow-up action has not been executed")
        success_count = sum(
            observation.status == ObservationStatus.SUCCESS
            for observation in state.observations
        )
        if success_count < self._minimum_successful_actions:
            issues.append(
                "Not enough successful actions: "
                f"required={self._minimum_successful_actions}, actual={success_count}"
            )
        required_types = set(self._required_artifact_types)
        for artifact_type, keywords in self._required_if_keywords.items():
            if any(keyword in state.goal for keyword in keywords):
                required_types.add(artifact_type)
        references = artifact_store.references(tuple(state.artifact_ids))
        available_types = {item.artifact_type for item in references}
        missing_types = required_types - available_types
        if missing_types:
            issues.append(
                "Missing required artifact types: " + ", ".join(sorted(missing_types))
            )
        if "learning_note_bundle" in required_types:
            expected_sources = max(
                (
                    int(observation.payload.get("success_count", 0))
                    for observation in state.observations
                    if observation.payload.get("tool_name") == "extract_resources_batch"
                ),
                default=0,
            )
            completed_sources = {
                str(observation.payload.get("source_identity", "")).strip()
                for observation in state.observations
                if (
                    observation.payload.get("tool_name") == "build_learning_note"
                    and observation.payload.get("completed_item") is True
                )
            }
            completed_sources.discard("")
            if expected_sources and len(completed_sources) < expected_sources:
                issues.append(
                    "Not all extracted resources have notes: "
                    f"expected={expected_sources}, completed={len(completed_sources)}"
                )
        return CompletionValidation(accepted=not issues, issues=tuple(issues))
