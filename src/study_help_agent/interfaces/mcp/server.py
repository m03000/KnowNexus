"""personal_agent 的 MCP Streamable HTTP 服务器定义。

MCP 层只声明给外部模型看的工具名称、描述和参数，业务实现继续位于 Capability。
服务器由主 FastAPI 进程挂载，不会出现两个进程直接争用本地 Qdrant 的问题。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

from .tools import (
    capture_external_turn as capture_turn_impl,
    flush_external_memory as flush_memory_impl,
    search_personal_knowledge as search_impl,
    trace_memory as trace_impl,
)

if TYPE_CHECKING:
    from study_help_agent.app.container import AppContainer


def create_mcp_server(container_provider: Callable[[], AppContainer]) -> FastMCP:
    """创建无状态 MCP 协议适配器，运行期按需取得 FastAPI 的共享容器。"""

    server = FastMCP(
        name="personal-agent-knowledge-base",
        instructions=(
            "这是用户的本地个人知识库。优先使用 search_personal_knowledge 检索代码、笔记和长期记忆；"
            "需要核验某条长期记忆的原始依据时使用 trace_memory。"
            "客户端对话对话由监听器自动保存，只有在用户允许且能够提供"
            "完整用户/助手轮次时才调用 capture_external_turn。"
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    @server.tool(
        name="search_personal_knowledge",
        description=(
            "在用户本地知识库中检索。底层会自行路由到项目代码、个人笔记或长期记忆，"
            "并组合关键词、向量以及适用时的图检索，再返回经过审查和重排的证据块。"
            "当问题依赖用户已有项目、笔记、偏好、决策或历史事实时调用。"
        ),
    )
    def search_personal_knowledge(
        query: str,
        history_context: str = "",
        top_k: int = 5,
        recall_k: int = 15,
    ) -> dict:
        return search_impl(
            container_provider(), query=query, history_context=history_context,
            top_k=top_k, recall_k=recall_k,
        )

    @server.tool(
        name="trace_memory",
        description=(
            "按 memory_id 查看一条长期记忆的完整证据链，包括原始对话消息、来源会话"
            "和时间线。用于确认记忆是否准确或解释它来自哪里；不要把它当普通搜索。"
        ),
    )
    def trace_memory(memory_id: str) -> dict:
        return trace_impl(container_provider(), memory_id=memory_id)

    @server.tool(
        name="capture_external_turn",
        description=(
            "把一个外部智能体已经完成的完整用户-助手轮次保存到本地长期记忆管线。"
            "调用方必须提供稳定的 client/session/turn ID；重复调用是幂等的。"
        ),
    )
    def capture_external_turn(
        client: str,
        external_session_id: str,
        external_turn_id: str,
        user_message: str,
        assistant_message: str,
        cwd: str = "",
        model: str = "",
        force_consolidation: bool = False,
    ) -> dict:
        return capture_turn_impl(
            container_provider(), client=client,
            external_session_id=external_session_id,
            external_turn_id=external_turn_id,
            user_message=user_message, assistant_message=assistant_message,
            cwd=cwd, model=model, force_consolidation=force_consolidation,
        )

    @server.tool(
        name="flush_external_memory",
        description=(
            "强制蒸馏指定外部会话尚未处理的原始轮次。"
            "适合会话结束或历史批量导入后调用；正常逐轮保存会按 3-5 轮批次自动触发，无需每轮调用。"
        ),
    )
    def flush_external_memory(client: str, external_session_id: str) -> dict:
        return flush_memory_impl(
            container_provider(), client=client,
            external_session_id=external_session_id,
        )

    return server
