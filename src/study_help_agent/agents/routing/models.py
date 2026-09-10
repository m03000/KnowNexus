from dataclasses import dataclass
from enum import StrEnum


class RequestIntent(StrEnum):
    CODE = "code"
    NOTE = "note"
    RAG = "rag"
    CHAT = "chat"
    COMPLEX = "complex"


@dataclass(frozen=True, slots=True)
class RouteDecision:
    intent: RequestIntent
    confidence: float
    reason: str
    profile_key: str | None = None
    requires_main_loop: bool = False