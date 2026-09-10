"""Loop Agent 的工具协议、注册表和统一执行器。

工具负责确定性动作，LLM 只能选择工具和提供参数。注册表暴露能力说明，执行器统一
完成名称查找、参数基础校验、异常隔离和 Observation 构建。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from time import perf_counter
from typing import TYPE_CHECKING, Any

from study_help_agent.runtime.artifacts.store import ArtifactStore
from study_help_agent.runtime.state import Observation, ObservationStatus
from study_help_agent.runtime.cancellation import AgentCancelledError
from study_help_agent.observability import get_observability_recorder, trace_scope

if TYPE_CHECKING:
    from study_help_agent.runtime.hooks.protocols import ToolResultObserver
    from study_help_agent.runtime.loop import EventSink
    from study_help_agent.runtime.cancellation import CancellationToken


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """向工具提供当前运行身份和 Artifact Store，不暴露整个 Agent 状态。"""

    run_id: str
    artifact_store: ArtifactStore
    event_sink: "EventSink | None" = None
    cancellation_token: "CancellationToken | None" = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具实现返回的标准结果，之后会被转换成 Observation。"""

    summary: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    artifact_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    partial: bool = False
    retryable: bool = False


ToolHandler = Callable[[Mapping[str, Any], ToolExecutionContext], ToolResult]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """描述一个可供 LLM 选择的原子工具及其参数 Schema。"""

    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: ToolHandler

    def prompt_schema(self) -> Mapping[str, Any]:
        """返回不包含 Python handler 的 LLM 可见工具说明。"""

        return {
            "name": self.name,
            "description": self.description,
            "parameters": dict(self.parameters),
        }


class ToolRegistry:
    """集中注册和查询工具，防止 Agent 调用未授权能力。"""

    def __init__(self) -> None:
        """初始化空注册表。"""

        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """注册一个工具；空名称和重复名称都会被拒绝。"""

        name = tool.name.strip()
        if not name:
            raise ValueError("Tool name cannot be empty")
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = tool

    def register_many(self, tools: Iterable[ToolDefinition]) -> None:
        """批量注册工具，并沿用单个注册的校验规则。"""

        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> ToolDefinition:
        """读取已授权工具；未知工具会抛出明确错误。"""

        try:
            return self._tools[name]
        except KeyError as error:
            raise KeyError(f"Tool not registered: {name}") from error

    def schemas(self) -> tuple[Mapping[str, Any], ...]:
        """返回全部 LLM 可见工具说明。"""

        return tuple(tool.prompt_schema() for tool in self._tools.values())

    def select(self, names: tuple[str, ...]) -> "ToolRegistry":
        """创建只包含指定工具的权限视图，未知名称立即失败。"""

        selected = ToolRegistry()
        selected.register_many(self.get(name) for name in names)
        return selected

    def names(self) -> tuple[str, ...]:
        """返回当前注册表中的稳定工具名称。"""

        return tuple(self._tools)


class ToolExecutor:
    """执行工具并把成功、部分成功或异常统一转成 Observation。"""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        artifact_store: ArtifactStore,
        result_observers: Iterable["ToolResultObserver"] = (),
        event_sink: "EventSink | None" = None,
        cancellation_token: "CancellationToken | None" = None,
    ) -> None:
        """保存工具注册表和工具可使用的产物存储。"""

        self._registry = registry
        self._artifact_store = artifact_store
        self._result_observers = tuple(result_observers)
        self._event_sink = event_sink
        self._cancellation_token = cancellation_token

    def execute(
        self,
        *,
        run_id: str,
        action_index: int,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> Observation:
        """校验并调用指定工具，任何普通异常都会成为失败 Observation。"""

        started = perf_counter()
        observation: Observation | None = None
        try:
            if self._cancellation_token is not None:
                self._cancellation_token.raise_if_cancelled()
            # 从工具注册表中获取工具名称
            tool = self._registry.get(tool_name)
            # 首次校验
            self._validate_arguments(arguments=arguments, schema=tool.parameters)
            context = ToolExecutionContext(
                run_id=run_id,
                artifact_store=self._artifact_store,
                event_sink=self._event_sink,
                cancellation_token=self._cancellation_token,
            )
            result = tool.handler(
                arguments,
                context,
            )
            if self._cancellation_token is not None:
                self._cancellation_token.raise_if_cancelled()
            payload = dict(result.payload)
            payload.setdefault("tool_name", tool_name)
            warnings = list(result.warnings)
            for observer in self._result_observers:
                try:
                    enrichment = observer.after_success(
                        tool_name=tool_name,
                        result=result,
                        context=context,
                    )
                    payload.update(enrichment.payload)
                    warnings.extend(enrichment.warnings)
                except Exception as observer_error:
                    # 自动入库属于旁路基础设施，故障不能把已经完成的业务工具改成失败。
                    warnings.append(
                        "Post-tool observer failed: "
                        f"{type(observer_error).__name__}: {observer_error}"
                    )
            status = (
                ObservationStatus.PARTIAL if result.partial else ObservationStatus.SUCCESS
            )
            observation = self._observation(
                run_id=run_id,
                action_index=action_index,
                status=status,
                summary=result.summary,
                payload=payload,
                artifact_ids=result.artifact_ids,
                warnings=tuple(warnings),
                retryable=result.retryable,
            )
            return observation
        except AgentCancelledError:
            raise
        except Exception as error:
            normalized_error = str(error).lower()
            terminal = isinstance(error, PermissionError) or any(
                marker in normalized_error
                for marker in (
                    "fresh cookies", "login required", "sign in to confirm", "private video",
                    "could not copy chrome cookie database",
                )
            )
            observation = self._observation(
                run_id=run_id,
                action_index=action_index,
                status=ObservationStatus.FAILED,
                summary=f"Tool {tool_name} failed: {error}",
                payload={
                    "tool_name": tool_name,
                    "error_type": type(error).__name__,
                    "terminal": terminal,
                },
                retryable=isinstance(error, (OSError, TimeoutError)),
            )
            return observation
        finally:
            if observation is not None:
                payload = dict(observation.payload)
                try:
                    with trace_scope(stage=f"tool:{tool_name}"):
                        get_observability_recorder().record(
                            "tool_finished",
                            status=observation.status.value,
                            duration_ms=round((perf_counter() - started) * 1000),
                            data={
                                "tool_name": tool_name,
                                "action_index": action_index,
                                "arguments": dict(arguments),
                                "summary": observation.summary,
                                "artifact_ids": list(observation.artifact_ids),
                                "retryable": observation.retryable,
                                **payload,
                            },
                        )
                except Exception:
                    pass

    @staticmethod
    def _validate_arguments(
        *, arguments: Mapping[str, Any], schema: Mapping[str, Any]
    ) -> None:
        """执行第一阶段所需的 required 和基础 JSON 类型校验。"""

        required = tuple(schema.get("required", ()))
        missing = [name for name in required if name not in arguments]
        if missing:
            raise ValueError(f"Missing required tool arguments: {missing}")
        properties = schema.get("properties", {})
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "object": Mapping,
            "array": (list, tuple),
        }
        for name, value in arguments.items():
            expected_name = properties.get(name, {}).get("type")
            expected = type_map.get(expected_name)
            if expected is not None and not isinstance(value, expected):
                raise TypeError(f"Argument {name} must be {expected_name}")

    @staticmethod
    def _observation(
        *,
        run_id: str,
        action_index: int,
        status: ObservationStatus,
        summary: str,
        payload: Mapping[str, Any],
        artifact_ids: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
        retryable: bool = False,
    ) -> Observation:
        """为 Observation 生成稳定且便于审计的 ID。"""

        digest = sha256(
            f"{run_id}|{action_index}|{status.value}|{summary}".encode("utf-8")
        ).hexdigest()[:20]
        return Observation(
            observation_id=f"observation_{digest}",
            action_index=action_index,
            status=status,
            summary=summary,
            payload=payload,
            artifact_ids=artifact_ids,
            warnings=warnings,
            retryable=retryable,
        )
