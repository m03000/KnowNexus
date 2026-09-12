"""LLM 客户端工厂。"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from openai import OpenAI

from study_help_agent.core.config import Settings
from study_help_agent.observability import ObservabilityLLMCallback


def _thinking_extra_body(model_name: str, thinking_mode: str) -> dict[str, object]:
    """仅向 DeepSeek 系列模型发送其专用 Thinking 参数。

    主 Agent 依赖 function calling，因此默认显式关闭 DeepSeek Thinking。
    千问等其他 OpenAI 兼容服务不接收该厂商专用字段。
    """

    if "deepseek" not in model_name.casefold():
        return {}
    return {"extra_body": {"thinking": {"type": thinking_mode}}}


def create_chat_model(settings: Settings) -> BaseChatModel:
    """创建供 LangChain/LangGraph 使用的聊天模型。"""

    return ChatOpenAI(
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        callbacks=[ObservabilityLLMCallback()],
        **_thinking_extra_body(settings.llm_model, settings.llm_thinking_mode),
    )


def create_openai_client(settings: Settings) -> OpenAI:
    """创建原生 OpenAI 兼容客户端。"""

    return OpenAI(
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


def reconfigure_chat_model(
    model: BaseChatModel,
    settings: Settings,
    *,
    api_key: str,
    base_url: str,
    model_name: str,
) -> None:
    """原位更新共享聊天模型，使所有已注入该实例的服务立即切换模型。"""

    replacement = ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model_name,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        callbacks=[ObservabilityLLMCallback()],
        **_thinking_extra_body(model_name, settings.llm_thinking_mode),
    )
    object.__setattr__(model, "__dict__", replacement.__dict__.copy())
    if hasattr(replacement, "__pydantic_private__"):
        object.__setattr__(model, "__pydantic_private__", replacement.__pydantic_private__)
