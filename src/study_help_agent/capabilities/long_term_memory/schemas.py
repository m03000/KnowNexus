"""对话记忆蒸馏的结构化输出 Schema。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class MemoryEntityCandidate(BaseModel):
    """从记忆点中提取的受控实体，禁止模型自由创造实体类型。"""

    name: str
    entity_type: Literal["project", "technology", "goal", "preference", "topic"]


class MemoryRelationCandidate(BaseModel):
    """新记忆与候选旧记忆之间的语义关系。"""

    target_memory_id: str
    relation_type: Literal["SAME_TOPIC", "SUPPORTS", "UPDATES", "CONTRADICTS"]
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class DistillationItem(BaseModel):
    """一条待落库的记忆点候选。

    operation 语义：
    - add：全新信息，落新记忆点；
    - update：已有记忆的同主题细化/重申，刷新原记忆点；
    - delete：用户明确作废的偏好，软删除原记忆点；
    - noop：本轮对话没有值得沉淀的信息。
    """

    operation: Literal["add", "update", "delete", "noop"] = "noop"
    content: str = ""
    summary: str = ""
    memory_type: Literal["preference", "goal", "decision", "fact", "learning"] = "fact"
    importance: int = Field(default=3, ge=1, le=5)
    subject: str = "user"
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    topics: list[str] = Field(default_factory=list)
    entities: list[MemoryEntityCandidate] = Field(default_factory=list)
    relations: list[MemoryRelationCandidate] = Field(default_factory=list)
    target_memory_id: str | None = Field(
        default=None,
        description=(
            "update/delete 时必须填写待更新或删除的旧记忆 ID；"
            "add/noop 时保持为空"
        ),
    )
    source_message_ids: list[int] = Field(
        default_factory=list,
        description="支持该记忆的待处理消息 ID",
    )


    @field_validator("topics")
    @classmethod
    def normalize_topics(cls, values: list[str]) -> list[str]:
        seen: list[str] = []
        for topic in values:
            cleaned = topic.strip()
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
        return seen[:5]

    @field_validator("source_message_ids")
    @classmethod
    def normalize_source_ids(
        cls,
        values: list[int],
    ) -> list[int]:
        return sorted(
            set(
                value
                for value in values
                if value > 0
            )
        )


class TurnDistillation(BaseModel):
    """一个完整用户轮次的独立蒸馏结果。

    一次 LLM 请求可以批量处理多个轮次，但每个 items 只能描述当前
    user/assistant 消息对，避免把不同轮次压缩成一条笼统记忆。
    """

    user_message_id: int = Field(gt=0)
    assistant_message_id: int = Field(gt=0)
    conversation_title: str = Field(
        default="",
        # 给模型输出留容错空间，最终展示层统一截断；不能因多写几个字让
        # 整批对话的结构化输出全部作废。
        max_length=80,
        description="不超过 20 字的本轮对话核心主题，用于目录和记忆星点标签",
    )
    display_summary: str = Field(
        default="",
        max_length=4000,
        description=(
            "本轮对话概括：普通对话 100～300 字，长对话最多 800 字；"
            "保留用户目标、关键结论和明确决定"
        ),
    )
    items: list[DistillationItem] = Field(default_factory=list)


class DistillationOutput(BaseModel):
    """一次批量调用返回的逐轮长期记忆蒸馏结果。"""

    turns: list[TurnDistillation] = Field(default_factory=list)
