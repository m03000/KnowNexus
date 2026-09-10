"""Learning 工具目录：汇总学习笔记 Provider，不包含固定调用流程。"""

from __future__ import annotations

from typing import Protocol

from study_help_agent.capabilities.learning_notes.application.service import LearningNoteService
from study_help_agent.capabilities.learning_notes.application.resource_service import (
    LearningResourceService,
)
from study_help_agent.capabilities.learning_notes.llm import (
    LearningContentNormalizerOperations,
)
from study_help_agent.capabilities.learning_notes.mini_agents import (
    LearningNoteBuilderMiniAgent,
)
from study_help_agent.runtime.tools import ToolDefinition

from .note_builder import LearningNoteBuilderTools
from .resource_processing import LearningResourceTools
from .batch_pipeline import LearningNotePipelineTools


class _ToolProvider(Protocol):
    """Learning catalog 接受的最小 Provider 结构。"""

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """返回此 Provider 拥有的工具定义。"""


def create_learning_tool_groups(
    *,
    note_service: LearningNoteService,
    note_builder_mini_agent: LearningNoteBuilderMiniAgent,
    resource_service: LearningResourceService,
    content_normalizer: LearningContentNormalizerOperations,
) -> tuple[tuple[ToolDefinition, ...], ...]:
    """创建默认生成与只读工具清单，不包含任何持久化修改能力。"""

    resource_tools = LearningResourceTools(
        service=resource_service,
        normalizer=content_normalizer,
    )
    note_tools = LearningNoteBuilderTools(
        mini_agent=note_builder_mini_agent,
        note_service=note_service,
    )
    providers: tuple[_ToolProvider, ...] = (
        resource_tools,
        note_tools,
        LearningNotePipelineTools(resources=resource_tools, notes=note_tools),
    )
    return tuple(provider.definitions() for provider in providers)
