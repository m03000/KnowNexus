"""Codex 对话自动捕获的轻量过滤策略。

过滤发生在完整轮次组装之后、写入本地暂存队列之前。默认策略不丢弃任何正常
对话；目录限制和闲聊过滤必须由用户显式启用。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .models import CapturedTurn

_CASUAL_MESSAGES = {
    "你好",
    "您好",
    "在吗",
    "谢谢",
    "谢谢你",
    "好的",
    "知道了",
    "再见",
}

_INTERNAL_PROMPT_PREFIXES = (
    "the following is the codex agent history",
    "the following is the codex agent history added since",
)


def _split_paths(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(os.pathsep) if item.strip())


def _normalize_path(value: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(value.strip())))


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class CapturePolicy:
    """按工作目录、输入长度和保守闲聊规则决定是否捕获完整轮次。"""

    include_cwds: tuple[str, ...] = ()
    exclude_cwds: tuple[str, ...] = ()
    min_prompt_length: int = 1
    capture_casual: bool = True
    capture_subagents: bool = False

    @classmethod
    def from_env(cls) -> "CapturePolicy":
        """从环境变量创建策略；默认保持完整捕获。"""

        return cls(
            include_cwds=_split_paths(os.getenv("PERSONAL_AGENT_CODEX_INCLUDE_CWD", "")),
            exclude_cwds=_split_paths(os.getenv("PERSONAL_AGENT_CODEX_EXCLUDE_CWD", "")),
            min_prompt_length=max(
                1, int(os.getenv("PERSONAL_AGENT_CODEX_MIN_PROMPT_LENGTH", "1"))
            ),
            capture_casual=_env_bool("PERSONAL_AGENT_CODEX_CAPTURE_CASUAL", True),
            capture_subagents=_env_bool("PERSONAL_AGENT_CODEX_CAPTURE_SUBAGENTS", False),
        )

    def allows(self, turn: CapturedTurn) -> tuple[bool, str]:
        """返回是否允许捕获，以及适合写入运行日志的原因。"""

        prompt = turn.prompt.strip()
        if prompt.casefold().startswith(_INTERNAL_PROMPT_PREFIXES):
            return False, "codex_internal_review"
        thread_source = str(turn.metadata.get("codex_thread_source") or "").casefold()
        session_source = str(turn.metadata.get("codex_session_source") or "").casefold()
        if not self.capture_subagents and (
            thread_source == "subagent" or session_source == "subagent"
        ):
            return False, "codex_subagent_session"
        if len(prompt) < self.min_prompt_length:
            return False, "prompt_too_short"

        cwd = _normalize_path(turn.cwd) if turn.cwd.strip() else ""
        includes = tuple(_normalize_path(path) for path in self.include_cwds)
        excludes = tuple(_normalize_path(path) for path in self.exclude_cwds)
        if includes and (not cwd or not any(_is_within(cwd, root) for root in includes)):
            return False, "cwd_not_included"
        if cwd and any(_is_within(cwd, root) for root in excludes):
            return False, "cwd_excluded"

        if not self.capture_casual and _is_casual(prompt):
            return False, "casual_message"
        return True, "allowed"


def _is_within(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _is_casual(prompt: str) -> bool:
    normalized = re.sub(r"[\s，。！？!?、,.]", "", prompt).lower()
    return normalized in _CASUAL_MESSAGES
