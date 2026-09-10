"""查询改写和检索结果审查的结构化输出。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class QueryRewriteOutput(BaseModel):
    """LLM 生成的独立、适合检索的查询。"""

    query: str = Field(min_length=3)


class QueryRouteOutput(BaseModel):
    """LLM 对检索空间的受控选择；枚举阻止其访问任意 Collection。"""

    target_spaces: list[
        Literal["project_code", "personal_knowledge", "user_memory"]
    ] = Field(min_length=1, max_length=3)
    reason: str = ""

    @field_validator("target_spaces")
    @classmethod
    def unique_spaces(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


class RetrievalReviewOutput(BaseModel):
    """审查重排结果是否真的能够支撑用户问题。"""

    relevant_chunk_ids: list[str] = Field(default_factory=list)
    sufficient: bool = False
    summary: str = ""
    issues: list[str] = Field(default_factory=list)

    @field_validator("relevant_chunk_ids")
    @classmethod
    def unique_ids(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))
