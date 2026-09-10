"""LLM 客户端工厂。

这里负责根据 Settings 创建具体模型客户端。
业务模块不应该自己读取环境变量。
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from openai import OpenAI

from study_help_agent.core.config import Settings
from study_help_agent.observability import ObservabilityLLMCallback


def create_chat_model(settings: Settings) -> BaseChatModel:
    """创建供 LangChain/LangGraph 使用的聊天模型。"""

    return ChatOpenAI(
        api_key=(
            settings
            .llm_api_key
            .get_secret_value()
        ),
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        callbacks=[ObservabilityLLMCallback()],
        extra_body={
            "thinking": {
                "type": (
                    settings.llm_thinking_mode
                )
            }
        },
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
        extra_body={"thinking": {"type": settings.llm_thinking_mode}},
    )
    object.__setattr__(model, "__dict__", replacement.__dict__.copy())
    if hasattr(replacement, "__pydantic_private__"):
        object.__setattr__(model, "__pydantic_private__", replacement.__pydantic_private__)
