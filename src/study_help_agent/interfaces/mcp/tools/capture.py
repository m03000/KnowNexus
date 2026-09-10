"""MCP 手动对话捕获工具。

没有原生生命周期 Hook 的客户端需主动调用此工具；Codex 默认仍使用 Hook 自动捕获。
"""

from __future__ import annotations

from study_help_agent.capabilities.external_conversation import ExternalConversationTurn


def capture_external_turn(
    container,
    *,
    client: str,
    external_session_id: str,
    external_turn_id: str,
    user_message: str,
    assistant_message: str,
    cwd: str = "",
    model: str = "",
    force_consolidation: bool = False,
) -> dict:
    """保存一轮完整外部对话；相同客户端、会话和轮次 ID 可安全重试。"""

    result = container.external_conversation_capture_service.capture_turn(
        ExternalConversationTurn(
            client=client,
            external_session_id=external_session_id,
            external_turn_id=external_turn_id,
            user_message=user_message,
            assistant_message=assistant_message,
            cwd=cwd,
            model=model,
        ),
        force_consolidation=force_consolidation,
    )
    return {
        "session_id": result.session_id,
        "turn_id": result.turn_id,
        "duplicate": result.duplicate,
        "user_message_id": result.user_message_id,
        "assistant_message_id": result.assistant_message_id,
        "consolidation": result.consolidation,
    }


def flush_external_memory(
    container, *, client: str, external_session_id: str
) -> dict:
    """强制将一个外部会话尚未处理的原始消息蒸馏为长期记忆。"""

    return container.external_conversation_capture_service.flush_session(
        client=client,
        external_session_id=external_session_id,
    )
