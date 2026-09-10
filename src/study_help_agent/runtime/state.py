"""Loop Agent 的核心数据协议。

本文件只定义运行状态、动作和观察结果，不执行任何业务逻辑。
统一的数据协议让LLM、工具执行器、预算策略和完成验收可以彼此替换。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class LoopRunStatus(StrEnum):
    """描述一次 Agent Loop 当前处于运行、完成还是受阻状态。"""

    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"


class ObservationStatus(StrEnum):
    """描述一次动作执行后得到的观察结果是否成功。"""

    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class ToolCallAction:
    """表示 LLM 决定调用一个已注册工具。"""

    tool_name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    purpose: str = ""


@dataclass(frozen=True, slots=True)
class FinishAction:
    """表示 LLM 认为目标已经完成，并向 Runtime 申请结束。"""

    answer: str
    completion_summary: str


@dataclass(frozen=True, slots=True)
class RequestUserInputAction:
    """表示缺少必须由用户提供的信息，当前运行需要暂停。"""

    question: str
    reason: str


@dataclass(frozen=True, slots=True)
class LoadSkillAction:
    """表示 LLM 决定按需加载一个流程 Skill，而不是立即执行工具。"""

    skill_name: str
    purpose: str = ""


AgentAction = ToolCallAction | FinishAction | RequestUserInputAction | LoadSkillAction


@dataclass(frozen=True, slots=True)
class AgentDecision:
    """保存 LLM 某一轮的简短判断和唯一下一步动作。"""

    reasoning_summary: str
    action: AgentAction


@dataclass(frozen=True, slots=True)
class Observation:
    """把工具结果、验收失败或 Runtime 事件包装成统一反馈。"""

    observation_id: str
    action_index: int
    status: ObservationStatus
    summary: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    artifact_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    """提供给 LLM 的轻量产物引用，避免把大内容反复塞进上下文。"""

    artifact_id: str
    artifact_type: str
    name: str
    summary: str


@dataclass(frozen=True, slots=True)
class AgentLoopContext:
    """某一轮交给决策器的受控上下文快照。"""

    run_id: str
    goal: str
    iteration: int
    recent_observations: tuple[Observation, ...]
    artifacts: tuple[ArtifactReference, ...]
    available_tools: tuple[Mapping[str, Any], ...]
    remaining_iterations: int
    remaining_tool_calls: int
    available_skills: tuple[Mapping[str, Any], ...] = ()
    loaded_skills: tuple[Mapping[str, Any], ...] = ()
    finalizing: bool = False
    finalization_hint: str = ""


@dataclass(slots=True)
class AgentRunState:
    """保存一次 Loop 的可变工作记忆、轨迹、预算消耗和最终结果。"""

    run_id: str
    goal: str
    status: LoopRunStatus = LoopRunStatus.RUNNING
    iteration: int = 0
    tool_calls: int = 0
    observations: list[Observation] = field(default_factory=list)
    decisions: list[AgentDecision] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    final_answer: str | None = None
    blocked_question: str | None = None
    repeated_action_count: int = 0
    loaded_skill_names: list[str] = field(default_factory=list)
    task_completed: bool = False
    finalization_fallback_answer: str = ""

    def record_decision(self, decision: AgentDecision) -> None:
        """记录一轮决策，并把迭代次数向前推进。"""

        self.decisions.append(decision)
        self.iteration += 1

    def record_observation(self, observation: Observation) -> None:
        """记录动作反馈，并收集反馈中产生的 Artifact 引用。"""

        self.observations.append(observation)
        for artifact_id in observation.artifact_ids:
            if artifact_id not in self.artifact_ids:
                self.artifact_ids.append(artifact_id)
