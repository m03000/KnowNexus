"""Code Analysis 模型调用的临时日志计量器。

计量器通过 LangChain callback 读取 provider 返回的 Token usage，并为每次调用记录
阶段、文件、批次、耗时和 Token。当前只写应用日志，不引入数据库或业务状态。
"""

from __future__ import annotations

import logging
from threading import Lock
from time import perf_counter
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)


class TokenUsageCallback(BaseCallbackHandler):
    """从普通及结构化 LangChain 响应中收集累计 Token usage。"""

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self._lock = Lock()

    def on_llm_end(self, response, **kwargs: Any) -> None:
        usage = self._extract_usage(response)
        with self._lock:
            self.input_tokens += int(
                usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
            )
            self.output_tokens += int(
                usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
            )
            self.total_tokens += int(usage.get("total_tokens", 0) or 0)

    @staticmethod
    def _extract_usage(response) -> dict[str, Any]:
        llm_output = getattr(response, "llm_output", None) or {}
        usage = llm_output.get("token_usage") or llm_output.get("usage")
        if usage:
            return dict(usage)
        for generation_group in getattr(response, "generations", ()):
            for generation in generation_group:
                message = getattr(generation, "message", None)
                message_usage = getattr(message, "usage_metadata", None)
                if message_usage:
                    return dict(message_usage)
                metadata = getattr(message, "response_metadata", None) or {}
                nested = metadata.get("token_usage") or metadata.get("usage")
                if nested:
                    return dict(nested)
        return {}


def invoke_with_cost_log(
    runnable,
    input_value,
    *,
    stage: str,
    file_path: str = "",
    batch_index: int | None = None,
    block_count: int | None = None,
):
    """执行一次模型调用，并在结束后输出一条结构化成本日志。"""

    usage = TokenUsageCallback()
    started = perf_counter()
    status = "success"
    try:
        return runnable.invoke(
            input_value,
            config={
                "callbacks": [usage],
                "tags": ["code_analysis", stage],
                "metadata": {
                    "stage": stage,
                    "file_path": file_path,
                    "batch_index": batch_index,
                },
            },
        )
    except Exception:
        status = "failed"
        raise
    finally:
        total = usage.total_tokens or usage.input_tokens + usage.output_tokens
        logger.info(
            "code_llm_cost stage=%s file=%s batch=%s blocks=%s status=%s "
            "input_tokens=%s output_tokens=%s total_tokens=%s duration_ms=%d",
            stage,
            file_path or "-",
            batch_index if batch_index is not None else "-",
            block_count if block_count is not None else "-",
            status,
            usage.input_tokens,
            usage.output_tokens,
            total,
            round((perf_counter() - started) * 1000),
        )
