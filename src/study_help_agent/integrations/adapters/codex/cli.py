"""Codex 会话适配器的独立命令行入口。"""

from __future__ import annotations

import argparse
import logging
import os
import signal
from pathlib import Path

from .filters import CapturePolicy
from .adapter import CodexConversationAdapter, default_sessions_dir


def build_parser() -> argparse.ArgumentParser:
    """创建轻量 CLI，不加载 FastAPI、LLM 或向量库。"""

    parser = argparse.ArgumentParser(description="Capture completed Codex turns")
    parser.add_argument(
        "--sessions-dir",
        type=Path,
        default=Path(os.getenv("CODEX_SESSIONS_DIR", str(default_sessions_dir()))),
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.getenv("PERSONAL_AGENT_CODEX_POLL_INTERVAL", "3.0")),
    )
    parser.add_argument(
        "--full-scan-interval",
        type=float,
        default=float(os.getenv("PERSONAL_AGENT_CODEX_FULL_SCAN_INTERVAL", "60.0")),
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="首次启动时导入已有 rollout 文件；默认只监听启动后的新内容",
    )
    parser.add_argument("--once", action="store_true", help="只扫描一次，用于诊断")
    return parser


def main() -> int:
    """启动增量监听；不修改 Codex 自身文件。"""

    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    watcher = CodexConversationAdapter(
        sessions_dir=args.sessions_dir,
        poll_interval=args.poll_interval,
        full_scan_interval=args.full_scan_interval,
        backfill=args.backfill,
        policy=CapturePolicy.from_env(),
    )
    for signal_name in ("SIGINT", "SIGTERM"):
        watched_signal = getattr(signal, signal_name, None)
        if watched_signal is not None:
            signal.signal(watched_signal, lambda *_: watcher.request_stop())
    try:
        if args.once:
            watcher.scan_once()
        else:
            watcher.run_forever()
    except KeyboardInterrupt:
        watcher.request_stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
