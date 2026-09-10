"""LangChain 模型回调：统一统计所有 Agent 的 Token、耗时和失败。"""

from __future__ import annotations

import os
from threading import Lock
from time import perf_counter
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from .context import current_trace
from .recorder import get_observability_recorder


class ObservabilityLLMCallback(BaseCallbackHandler):
    """附加在共享 ChatModel 上，避免逐个修改 LLM 调用点。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._calls: dict[str, tuple[float, dict[str, str]]] = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs: Any) -> None:
        self._start(run_id, serialized, kwargs)

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs: Any) -> None:
        self._start(run_id, serialized, kwargs)

    def on_llm_end(self, response, *, run_id, **kwargs: Any) -> None:
        started, metadata = self._pop(run_id)
        usage = self._extract_usage(response)
        input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
        output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
        total_tokens = int(usage.get("total_tokens", 0) or input_tokens + output_tokens)
        get_observability_recorder().record(
            "llm_finished", status="success",
            duration_ms=round((perf_counter() - started) * 1000),
            data={**metadata, "input_tokens": input_tokens,
                  "output_tokens": output_tokens, "total_tokens": total_tokens,
                  "estimated_cost": self._estimate_cost(input_tokens, output_tokens)},
        )

    def on_llm_error(self, error: BaseException, *, run_id, **kwargs: Any) -> None:
        started, metadata = self._pop(run_id)
        get_observability_recorder().record(
            "llm_finished", status="failed",
            duration_ms=round((perf_counter() - started) * 1000),
            data={**metadata, "error": f"{type(error).__name__}: {error}"},
        )

    def _start(self, run_id: Any, serialized: dict[str, Any], kwargs: dict[str, Any]) -> None:
        context = current_trace()
        params = kwargs.get("invocation_params") or {}
        model = str(
            params.get("model") or params.get("model_name") or serialized.get("name")
            or serialized.get("id", ["unknown"])[-1]
        )
        with self._lock:
            self._calls[str(run_id)] = (
                perf_counter(), {"model": model, "agent": context.agent, "stage": context.stage},
            )

    def _pop(self, run_id: Any) -> tuple[float, dict[str, str]]:
        with self._lock:
            return self._calls.pop(str(run_id), (perf_counter(), {"model": "unknown"}))

    @staticmethod
    def _extract_usage(response: Any) -> dict[str, Any]:
        output = getattr(response, "llm_output", None) or {}
        usage = output.get("token_usage") or output.get("usage")
        if usage:
            return dict(usage)
        for group in getattr(response, "generations", ()):
            for generation in group:
                message = getattr(generation, "message", None)
                direct = getattr(message, "usage_metadata", None)
                if direct:
                    return dict(direct)
                metadata = getattr(message, "response_metadata", None) or {}
                nested = metadata.get("token_usage") or metadata.get("usage")
                if nested:
                    return dict(nested)
        return {}

    @staticmethod
    def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
        input_price = float(os.getenv("LLM_INPUT_PRICE_PER_MILLION", "0") or 0)
        output_price = float(os.getenv("LLM_OUTPUT_PRICE_PER_MILLION", "0") or 0)
        return round((input_tokens * input_price + output_tokens * output_price) / 1_000_000, 8)
