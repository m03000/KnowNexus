"""Codex 生命周期 Hook 命令入口。

命令从 stdin 读取官方 Hook JSON，先持久暂存再尝试投递，始终向 stdout 输出合法
JSON，不阻塞用户提示，不要求 Codex 继续执行。
"""

from __future__ import annotations

import json
import sys

from .client import CaptureApiClient
from .spool import HookSpool


def handle(payload: dict, *, spool: HookSpool, client: CaptureApiClient) -> None:
    """根据 hook_event_name 分流，并执行一次低延迟补偿投递。"""

    event = str(payload.get("hook_event_name") or "")
    if event == "UserPromptSubmit":
        spool.record_prompt(payload)
        client.drain(spool)
    elif event == "Stop":
        spool.record_stop(payload)
        client.drain(spool)
    elif event == "SessionEnd":
        client.drain(spool)
        session_id = str(payload.get("session_id") or "").strip()
        if session_id:
            try:
                client.flush_session(session_id)
            except Exception:
                pass


def main() -> int:
    """控制台入口；捕获失败只写 stderr，绝不破坏 Codex 主流程。"""

    try:
        payload = json.load(sys.stdin)
        handle(payload, spool=HookSpool(), client=CaptureApiClient())
    except Exception as exc:
        print(f"personal_agent capture deferred: {exc}", file=sys.stderr)
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
