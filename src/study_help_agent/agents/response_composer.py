"""将 Agent 执行结果整理成面向用户的最终回答。

位于执行 Loop 之后，只读取已经产生的状态、观察结果和 Artifact 引用。
不持有工具注册表，也不能继续执行业务动作，因此不会把已完成任务重新带回 Loop。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from study_help_agent.runtime.state import AgentRunState


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResponseCompositionInput:
    """汇总层所需的最小只读输入，避免把完整运行对象暴露给模型。"""

    user_message: str
    execution_answer: str
    artifact_ids: tuple[str, ...]
    observation_summaries: tuple[str, ...]


class ResponseComposer:
    """在业务执行结束后生成一次最终答复，并在模型失败时可靠降级。"""

    def __init__(self, *, llm: BaseChatModel, max_observations: int = 8) -> None:
        self._llm = llm
        self._max_observations = max(1, max_observations)

    def compose(
        self,
        *,
        user_message: str,
        state: AgentRunState,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        """基于已完成执行结果生成回答；本方法绝不调用工具或修改 Loop 状态。"""

        fallback = self._fallback_answer(state)
        composition_input = ResponseCompositionInput(
            user_message=user_message.strip(),
            execution_answer=fallback,
            artifact_ids=tuple(state.artifact_ids),
            observation_summaries=tuple(
                observation.summary.strip()
                for observation in state.observations[-self._max_observations :]
                if observation.summary.strip()
            ),
        )
        streamed_parts: list[str] = []
        try:
            messages = [
                SystemMessage(content=self._system_prompt()),
                HumanMessage(content=self._render_input(composition_input)),
            ]
            if on_delta is None:
                answer = self._extract_text(self._llm.invoke(messages)).strip()
            else:
                for chunk in self._llm.stream(messages):
                    text = self._extract_text(chunk)
                    if not text:
                        continue
                    streamed_parts.append(text)
                    on_delta(text)
                answer = "".join(streamed_parts).strip()
                if not answer:
                    on_delta(fallback)
                    return fallback
            return answer or fallback
        except Exception:
            logger.warning("最终回答汇总失败，使用执行层结果兜底", exc_info=True)
            partial = "".join(streamed_parts).strip()
            if partial:
                return partial
            if on_delta is not None:
                on_delta(fallback)
            return fallback

    @staticmethod
    def _fallback_answer(state: AgentRunState) -> str:
        """选择不依赖额外模型调用的稳定兜底回答。"""

        return (
            (state.final_answer or "").strip()
            or state.finalization_fallback_answer.strip()
            or "任务已经执行完成，但没有产生可展示的结果。"
        )

    @staticmethod
    def _system_prompt() -> str:
        """限制汇总模型只组织语言，禁止虚构执行结果或提出新动作。"""

        return (
            "你是最终回答汇总器。业务 Agent 已经完成任务，你只能依据给定的执行结果组织面向用户的最终回答。"
            "不要调用工具，不要规划或继续执行任务，不要声称完成输入中未出现的操作。"
            "回答应先说明结果，再概括关键内容；存在多个产物时逐项说明，存在失败项时如实保留。"
            "不要输出内部推理、运行协议或 JSON。"
        )

    @staticmethod
    def _render_input(value: ResponseCompositionInput) -> str:
        """把有限执行信息渲染为紧凑提示，避免整段轨迹占用上下文。"""

        observations = "\n".join(f"- {item}" for item in value.observation_summaries)
        artifacts = ", ".join(value.artifact_ids) or "无"
        return (
            f"用户原始请求：\n{value.user_message}\n\n"
            f"执行层结果：\n{value.execution_answer}\n\n"
            f"产物 ID：{artifacts}\n\n"
            f"最近的有效执行摘要：\n{observations or '无'}"
        )

    @staticmethod
    def _extract_text(response: object) -> str:
        """兼容普通字符串及 LangChain AIMessage 的文本内容。"""

        content = getattr(response, "content", response)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "".join(parts)
        return str(content) if content is not None else ""
