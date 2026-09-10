"""面向 API 的 Main Agent 服务，并在一轮结束后协调两类独立记忆能力。"""

from dataclasses import asdict, dataclass
import logging
from typing import Callable, Protocol
from uuid import uuid4

from study_help_agent.agents.factory import AgentLoopFactory
from study_help_agent.agents.main.sessions import InMemoryConversationStore
from study_help_agent.agents.registry import AgentProfileRegistry
from study_help_agent.runtime.state import LoopRunStatus
from study_help_agent.agents.routing import MainIntentRouter
from study_help_agent.agents.response_composer import ResponseComposer
from study_help_agent.runtime.streaming import StreamEvent
from study_help_agent.runtime.cancellation import CancellationToken
logger = logging.getLogger(__name__)


class ConversationStore(Protocol):
    """无持久化环境使用的兼容会话端口。"""

    def build_goal(self, session_id: str, current_message: str) -> str: ...
    def append(self, session_id: str, *, role: str, content: str) -> None: ...


class ConversationContextPort(Protocol):
    """短期记忆端口：组装上下文并保存本轮原始消息。"""

    def build_goal(self, session_id: str, current_message: str) -> str: ...
    def get_recorded_turn(self, session_id: str, *,
                          turn_id: str) -> tuple[str, str] | None: ...
    def record_turn(self, session_id: str, *, user_message: str,
                    assistant_message: str, turn_id: str): ...
    def list_sessions(self, *, limit: int = 50) -> tuple[dict, ...]: ...
    def get_messages(self, session_id: str) -> tuple[dict, ...]: ...
    def delete_session(self, session_id: str) -> bool: ...
    def create_session(self, session_id: str, *, title: str = "新对话") -> dict: ...


class MemoryConsolidator(Protocol):
    """长期记忆端口：按策略批量蒸馏尚未处理的原始消息。"""

    def consolidate_if_needed(self, *, session_id: str,
                              force: bool = False) -> dict: ...


@dataclass(frozen=True, slots=True)
class MainAgentResponse:
    run_id: str
    session_id: str
    status: str
    final_reply: str
    blocked_question: str | None
    iterations: int
    tool_calls: int
    artifact_ids: tuple[str, ...]


class MainAgentService:
    """运行 Main Loop；应用层并列协调短期保存和长期蒸馏。"""

    def __init__(
        self,
        *,
        factory: AgentLoopFactory,
        profiles: AgentProfileRegistry,
        intent_router: MainIntentRouter | None = None,
        conversations: ConversationStore | None = None,
        conversation_context: ConversationContextPort | None = None,
        memory_consolidator: MemoryConsolidator | None = None,
        response_composer: ResponseComposer | None = None,
    ) -> None:
        self._factory = factory
        self._profiles = profiles
        self._intent_router = intent_router or MainIntentRouter()
        self._conversations = conversations or InMemoryConversationStore()
        self._conversation_context = conversation_context
        self._memory_consolidator = memory_consolidator
        self._response_composer = response_composer

    def run(
        self,
        *,
        message: str,
        session_id: str,
        turn_id: str | None = None,
        event_sink: Callable[[StreamEvent], None] | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> MainAgentResponse:
        # 校验信息
        goal = message.strip()
        if not goal:
            raise ValueError("用户消息不能为空")
        normalized_session = session_id.strip() or "default"
        if turn_id and turn_id.strip() and self._conversation_context is not None:
            recorded = self._conversation_context.get_recorded_turn(
                normalized_session, turn_id=turn_id.strip()
            )
            if recorded is not None:
                response = MainAgentResponse(
                    run_id=f"replay:{turn_id.strip()}",
                    session_id=normalized_session,
                    status=LoopRunStatus.COMPLETED.value,
                    final_reply=recorded[1],
                    blocked_question=None,
                    iterations=0,
                    tool_calls=0,
                    artifact_ids=(),
                )
                self._emit_stream_response(event_sink, response)
                return response
        run_id = f"main:{normalized_session}:{uuid4().hex}"
        # 加载起始思考事件
        self._emit(event_sink, "status", run_id, {"message": "正在理解请求"})
        normalized_turn_id = turn_id.strip() if turn_id and turn_id.strip() else run_id
        context_source = self._conversation_context or self._conversations
        contextual_goal = context_source.build_goal(normalized_session, goal)
        # 进行规则意图识别
        route = self._intent_router.route(goal)
        if route.requires_main_loop:
            profile_key = "main"
        else:
            profile_key = route.profile_key or "main"
        # 加载意图识别思考事件
        self._emit(
            event_sink,
            "route",
            run_id,
            {
                "profile": profile_key,
                "intent": route.intent.value,
                "reason": route.reason,
                "message": f"已选择 {profile_key} Agent",
            },
        )
        # 获取意图识别结果
        factory_arguments = {
            "profile_key": profile_key,
            "goal": contextual_goal,
            "run_id": run_id,
            "cancellation_token": cancellation_token,
        }
        if event_sink is not None:
            factory_arguments["event_sink"] = event_sink
        # 执行任务
        state = self._factory.run(
            **factory_arguments,
        )
        # 其他状况
        answer_streamed = False
        if state.status == LoopRunStatus.BLOCKED:
            reply = state.blocked_question or "需要补充信息后才能继续。"
        elif state.status == LoopRunStatus.BUDGET_EXHAUSTED:
            reply = "本次 Agent 运行已达到预算上限，请缩小任务范围后重试。"
        elif state.status == LoopRunStatus.CANCELLED:
            reply = "本次任务已取消，后续步骤和模型调用已经停止。"
        else:
            execution_reply = state.final_answer or "任务未产生最终回答。"
            if self._response_composer is None:
                reply = execution_reply
            else:
                self._emit(
                    event_sink,
                    "status",
                    state.run_id,
                    {"message": "正在整理最终回答", "stage": "response_composition"},
                )
                reply = self._response_composer.compose(
                    user_message=goal,
                    state=state,
                    on_delta=(
                        lambda text: self._emit(
                            event_sink, "answer_delta", state.run_id, {"text": text}
                        )
                    ) if event_sink is not None else None,
                )
                answer_streamed = event_sink is not None
        # 记忆处理
        if state.status == LoopRunStatus.CANCELLED:
            pass
        elif self._conversation_context is not None:
            self._conversation_context.record_turn(
                normalized_session, user_message=goal, assistant_message=reply,
                turn_id=normalized_turn_id,
            )
        else:
            self._conversations.append(normalized_session, role="user", content=goal)
            self._conversations.append(normalized_session, role="assistant", content=reply)
        # 并列触发长期后处理记忆模块
        if (
            state.status != LoopRunStatus.CANCELLED
            and self._memory_consolidator is not None
        ):
            try:
                self._memory_consolidator.consolidate_if_needed(
                    session_id=normalized_session
                )
            except Exception:
                logger.warning("长期记忆蒸馏调度异常", exc_info=True)
         # 组装回答结果
        response = MainAgentResponse(
            run_id=state.run_id, session_id=normalized_session,
            status=state.status.value, final_reply=reply,
            blocked_question=state.blocked_question, iterations=state.iteration,
            tool_calls=state.tool_calls, artifact_ids=tuple(state.artifact_ids),
        )
        self._emit_stream_response(
            event_sink,
            response,
            include_answer=not answer_streamed,
        )
        return response

    def _emit_stream_response(
        self,
        event_sink: Callable[[StreamEvent], None] | None,
        response: MainAgentResponse,
        *,
        include_answer: bool = True,
    ) -> None:
        """所有成功返回路径统一发送回答片段和显式终止事件。"""

        if event_sink is None:
            return
        if include_answer:
            for chunk in self._answer_chunks(response.final_reply):
                self._emit(event_sink, "answer_delta", response.run_id, {"text": chunk})
        self._emit(event_sink, "done", response.run_id, {"response": asdict(response)})

    @staticmethod
    def _answer_chunks(answer: str, size: int = 18) -> tuple[str, ...]:
        """把已验收回答切成稳定小片段，供当前结构化 Loop 流式传输。"""

        return tuple(answer[index:index + size] for index in range(0, len(answer), size))

    @staticmethod
    def _emit(
        sink: Callable[[StreamEvent], None] | None,
        event: str,
        run_id: str,
        data: dict,
    ) -> None:
        """事件展示是旁路能力，失败时不能破坏主业务。"""

        if sink is None:
            return
        try:
            sink(StreamEvent(event=event, run_id=run_id, data=data, agent="main"))
        except Exception:
            logger.debug("流式事件发送失败", exc_info=True)

    def profiles(self) -> tuple[dict[str, object], ...]:
        return self._profiles.definitions()

    def list_sessions(self) -> tuple[dict, ...]:
        """返回对话主页可见的内部会话目录。"""

        if self._conversation_context is None:
            return ()
        return self._conversation_context.list_sessions()

    def get_session_messages(self, session_id: str) -> tuple[dict, ...]:
        """读取一个内部会话的完整展示消息。"""

        if self._conversation_context is None:
            return ()
        return self._conversation_context.get_messages(session_id)

    def delete_session(self, session_id: str) -> bool:
        """删除一个网页内部短期会话。"""

        if self._conversation_context is None:
            return False
        return self._conversation_context.delete_session(session_id)
    def create_session(self, session_id: str, *, title: str = "新对话") -> dict:
        """立即创建网页会话，使会话生命周期不再依赖 Agent 是否完成。"""

        if self._conversation_context is None:
            raise RuntimeError("当前环境未配置持久化会话仓储")
        return self._conversation_context.create_session(session_id, title=title)
