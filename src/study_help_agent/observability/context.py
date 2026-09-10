"""在请求线程、Agent Loop 与模型回调之间传播 Trace 标识。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, Iterator, TypeVar


T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True, slots=True)
class TraceContext:
    """一次前端任务在当前执行上下文中的稳定关联标识。"""

    run_id: str = ""
    trace_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    parent_run_id: str = ""
    agent: str = "main"
    stage: str = ""


_TRACE_CONTEXT: ContextVar[TraceContext] = ContextVar(
    "study_help_agent_trace_context", default=TraceContext()
)


def current_trace() -> TraceContext:
    """读取当前 Trace；非请求后台任务得到空上下文。"""

    return _TRACE_CONTEXT.get()


@contextmanager
def trace_scope(**updates: str) -> Iterator[TraceContext]:
    """临时绑定 Trace 字段，并在离开作用域后恢复上层上下文。"""

    context = replace(current_trace(), **updates)
    token = _TRACE_CONTEXT.set(context)
    try:
        yield context
    finally:
        _TRACE_CONTEXT.reset(token)


def submit_with_trace(executor: Any, function: Callable[..., R], /, *args: Any, **kwargs: Any) -> Any:
    """向线程池提交任务，并把当前 TraceContext 复制到工作线程。"""

    context = copy_context()
    return executor.submit(context.run, function, *args, **kwargs)


def map_with_trace(
    executor: Any,
    function: Callable[[T], R],
    values: Iterable[T],
) -> list[R]:
    """保持输入顺序映射任务，并为每项复制独立的 TraceContext。"""

    futures = [submit_with_trace(executor, function, value) for value in values]
    return [future.result() for future in futures]
