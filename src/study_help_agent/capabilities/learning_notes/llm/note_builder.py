"""内容审查、动态笔记规划、专业化生成和质量复核的 LLM 操作。

模型先提取可追踪的信息单元，再基于局部审查生成全局结构规划。生成阶段必须引用规划
中的来源块和信息 ID，最后通过独立审查检查结构、忠实度与覆盖率。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from study_help_agent.infrastructure.llm.local_structured_output import (
    LocalStructuredOutput,
)

from .schemas import (
    ChunkAuditOutput,
    GeneratedPlannedNoteOutput,
    NotePlanOutput,
    NoteQualityReviewOutput,
)


class LearningNoteBuilderOperations:
    """封装分块审查、全局规划、按规划生成、审查和定向修订。"""

    def __init__(self, llm: BaseChatModel) -> None:
        self._chunk_auditor = LocalStructuredOutput(llm, ChunkAuditOutput)
        self._planner = LocalStructuredOutput(llm, NotePlanOutput)
        self._generator = LocalStructuredOutput(llm, GeneratedPlannedNoteOutput)
        self._reviewer = LocalStructuredOutput(llm, NoteQualityReviewOutput)

    def audit_chunk(self, *, chunk: dict[str, Any]) -> ChunkAuditOutput:
        """审查一个语义块的内容价值与局部结构，不提前撰写笔记。"""

        return self._chunk_auditor.invoke(
            "审查下面的来源内容块。识别核心主题、局部结构问题，并提取最多30个有效信息单元。"
            "信息单元应覆盖概念、事实、解释、例子、代码、步骤、数据、限制、警告和观点；不要按句子机械切分。"
            "item_id 使用 i001 这类块内短 ID。required 表示专业笔记不能遗漏，supporting 表示可合并表达。"
            "source_excerpt 只保留用于核验的短语，不要复制大段原文。\n"
            f"块ID：{chunk['chunk_id']}\n原始标题线索：{chunk.get('heading', '')}\n"
            f"内容：\n{chunk['text']}"
        )

    def plan_notes(
        self,
        *,
        scale: str,
        chunks: list[dict[str, Any]],
        audits: list[dict[str, Any]],
        inventory: list[dict[str, Any]],
    ) -> NotePlanOutput:
        """综合局部审查，动态决定结构调整方式和最终笔记数量。"""

        chunk_summary = [
            {
                "chunk_id": chunk["chunk_id"],
                "heading": chunk.get("heading", ""),
                "characters": chunk["character_count"],
            }
            for chunk in chunks
        ]
        return self._planner.invoke(
            "你是学习内容架构师。根据内容审查判断原材料的全局结构是否合理，并动态规划专业学习笔记。"
            "不能使用固定模板。可以保留、重命名、合并、拆分或重排原章节。"
            "每个章节必须填写真实 source_chunk_ids 和 required_item_ids。"
            "所有 required 信息单元必须且只能至少分配到一个合适章节。"
            "规划目标是专业重组而非照搬，也不是摘要。最多规划8篇笔记。\n"
            f"规模：{scale}\n块信息：{json.dumps(chunk_summary, ensure_ascii=False)}\n"
            f"局部审查：{json.dumps(audits, ensure_ascii=False)}\n"
            f"信息清单：{json.dumps(inventory, ensure_ascii=False)}"
        )

    def generate_note(
        self,
        *,
        plan: dict[str, Any],
        chunks: list[dict[str, Any]],
        inventory: list[dict[str, Any]],
        current_note: dict[str, Any] | None = None,
        feedback: list[str] | None = None,
    ) -> GeneratedPlannedNoteOutput:
        """按照动态规划将来源信息转化为一篇专业笔记或定向修订现有笔记。"""

        revision_context = ""
        if current_note is not None:
            revision_context = (
                "\n这是一次有界修订。保留当前正确内容，只解决反馈问题并补回遗漏。"
                f"\n修订反馈：{json.dumps(feedback or [], ensure_ascii=False)}"
                f"\n当前笔记：{json.dumps(current_note, ensure_ascii=False)}"
            )
        return self._generator.invoke(
            "根据规划和来源证据撰写完整 Markdown 学习笔记。必须重新组织为专业、连贯、可长期阅读的内容，而不是逐句照搬或压缩摘要。"
            "内容规模必须随来源有效信息量增长：较长视频或长文档必须保留更多解释、论证、示例、步骤、限制与上下文，不得把十分钟材料压成与两分钟材料相近的简短摘要。"
            "保留所有 required 信息以及有教学价值的 supporting 信息，合并重复表达，补足必要过渡，但不得添加来源没有的事实。"
            "代码、数据、例子、步骤、限制和警告必须放入合适章节。content 内使用规划的章节结构。"
            "标题只用于主要主题，## 二级标题不要规划太多；不要为每个短观点单独设标题。"
            "段落、列表及其缩进必须符合 Markdown。covered_item_ids 只能填写确实已体现在正文中的真实 ID。\n"
            f"笔记规划：{json.dumps(plan, ensure_ascii=False)}\n"
            f"信息清单：{json.dumps(inventory, ensure_ascii=False)}\n"
            f"来源块：{json.dumps(chunks, ensure_ascii=False)}"
            f"{revision_context}"
        )

    def review_note(
        self,
        *,
        plan: dict[str, Any],
        note: dict[str, Any],
        inventory: list[dict[str, Any]],
    ) -> NoteQualityReviewOutput:
        """独立检查最终结构、来源忠实度和信息覆盖，不负责重新生成正文。"""

        return self._reviewer.invoke(
            "独立审查这篇学习笔记。检查：结构是否符合材料内容而非固定模板；表达是否专业连贯；"
            "是否忠于信息清单；required 信息是否真正出现在正文；"
            "是否错误声称覆盖了某个 ID。missing_item_ids 只能使用信息清单中的 ID。"
            "只有结构、忠实度和覆盖度全部通过时 passed 才能为 true。"
            "长来源若被压成简短摘要、标题过密、使用十进制章节编号或列表缩进混乱，都必须判定不通过。\n"
            f"规划：{json.dumps(plan, ensure_ascii=False)}\n"
            f"信息清单：{json.dumps(inventory, ensure_ascii=False)}\n"
            f"待审查笔记：{json.dumps(note, ensure_ascii=False)}"
        )
