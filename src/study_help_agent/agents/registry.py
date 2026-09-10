"""定义具体 Agent Profile 的数据模型与注册表。

AgentProfile 只声明身份、系统指令、工具/Skill 白名单和预算，不包含业务执行代码。
各 Agent 的具体 Profile 分散在自己的目录，本文件只提供统一模型与查找能力。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from study_help_agent.runtime.budgets import LoopBudget


@dataclass(frozen=True, slots=True)
class AgentProfile:
    """描述一个 Loop Agent 的目标边界、能力白名单和运行预算。"""

    key: str
    name: str
    description: str
    system_instructions: str
    tool_names: tuple[str, ...]
    skill_names: tuple[str, ...]
    budget: LoopBudget
    minimum_successful_actions: int = 1
    required_artifact_types: tuple[str, ...] = ()
    required_if_keywords: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    complete_on_task_ready: bool = False


class AgentProfileRegistry:
    """集中注册 AgentProfile，并为 API 和委派工具提供稳定查询。"""

    def __init__(self) -> None:
        """初始化空 Profile 字典。"""

        self._profiles: dict[str, AgentProfile] = {}

    def register(self, profile: AgentProfile) -> None:
        """注册 Profile，拒绝空 key 和重复 key。"""

        key = profile.key.strip()
        if not key:
            raise ValueError("Agent profile key cannot be empty")
        if key in self._profiles:
            raise ValueError(f"Agent profile already registered: {key}")
        self._profiles[key] = profile

    def register_many(self, profiles: tuple[AgentProfile, ...]) -> None:
        """批量注册 Profile。"""

        for profile in profiles:
            self.register(profile)

    def get(self, key: str) -> AgentProfile:
        """读取指定 Profile。"""

        try:
            return self._profiles[key]
        except KeyError as error:
            raise KeyError(f"Agent profile not registered: {key}") from error

    def definitions(self) -> tuple[dict[str, object], ...]:
        """返回适合 API 展示的 Agent 能力摘要。"""

        return tuple({
            "key": item.key,
            "name": item.name,
            "description": item.description,
            "tools": list(item.tool_names),
            "skills": list(item.skill_names),
        } for item in self._profiles.values())
