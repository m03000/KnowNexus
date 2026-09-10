"""外部智能体对话接入 Capability 的公开 API。"""

from .application import ExternalConversationCaptureService
from .domain import CaptureResult, ExternalConversationTurn, OriginType

__all__ = [
    "CaptureResult",
    "ExternalConversationCaptureService",
    "ExternalConversationTurn",
    "OriginType",
]
