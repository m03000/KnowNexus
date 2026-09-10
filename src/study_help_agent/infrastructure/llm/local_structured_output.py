"""Structured output that does not depend on provider-specific API features."""

from typing import Any, Generic, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LocalStructuredOutput(Generic[SchemaT]):
    """Ask for JSON through the prompt and validate it locally with Pydantic."""

    def __init__(self, llm: BaseChatModel, schema: type[SchemaT]) -> None:
        self._llm = llm
        self._parser = PydanticOutputParser(pydantic_object=schema)
        self.last_usage: dict[str, int] = {}

    def invoke(self, prompt: str | list[BaseMessage], **kwargs: Any) -> SchemaT:
        instruction = (
            "请严格按照下面的 JSON Schema 返回一个 JSON 对象。"
            "不要调用工具，不要添加 JSON 之外的解释。\n"
            f"{self._parser.get_format_instructions()}"
        )
        if isinstance(prompt, str):
            model_input: str | list[BaseMessage] = f"{prompt}\n\n{instruction}"
        else:
            model_input = [SystemMessage(content=instruction), *prompt]

        response = self._llm.invoke(model_input, **kwargs)
        metadata = getattr(response, "usage_metadata", None) or {}
        response_metadata = getattr(response, "response_metadata", None) or {}
        provider_usage = response_metadata.get("token_usage") or response_metadata.get("usage") or {}
        usage = metadata or provider_usage
        self.last_usage = {
            "input_tokens": int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
        }
        self.last_usage["total_tokens"] = int(usage.get("total_tokens") or sum(self.last_usage.values()))
        content = getattr(response, "content", response)
        if not isinstance(content, str):
            raise TypeError(
                "LLM 结构化输出必须是文本，"
                f"实际得到 {type(content).__name__}"
            )
        # 部分本地或 OpenAI 兼容服务不返回 usage；仍为 Wiki 构建提供稳定的近似计数。
        if not self.last_usage["total_tokens"]:
            input_text = model_input if isinstance(model_input, str) else "\n".join(
                str(message.content) for message in model_input
            )
            self.last_usage["input_tokens"] = max(1, len(input_text) // 2)
            self.last_usage["output_tokens"] = max(1, len(content) // 2)
            self.last_usage["total_tokens"] = (
                self.last_usage["input_tokens"] + self.last_usage["output_tokens"]
            )
        return self._parser.parse(content)
