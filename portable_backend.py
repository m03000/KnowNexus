"""Entry point used by the Windows portable distribution."""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

import uvicorn


def _configure_portable_data_paths() -> None:
    """Keep writable state outside the read-only application bundle."""
    base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "KnowNexus"
    data = base / "data"
    os.environ.setdefault("DATABASE_PATH", str(data / "knownexus.db"))
    os.environ.setdefault("RUNTIME_DATA_DIRECTORY", str(data))
    os.environ.setdefault("RUNTIME_LOG_DIRECTORY", str(base / "logs"))
    os.environ.setdefault("RAG_MODEL_CACHE_DIRECTORY", str(base / "models" / "huggingface" / "hub"))
    os.environ.setdefault("LLM_API_KEY", "not-configured")


_configure_portable_data_paths()

from study_help_agent.app.main import app  # noqa: E402


def main() -> None:
    multiprocessing.freeze_support()
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
