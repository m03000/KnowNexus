"""Entry point used by the Windows portable distribution."""

from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path

import uvicorn


def _configure_portable_data_paths() -> None:
    """Keep writable state outside the read-only application bundle."""
    root = Path(sys.executable).resolve().parent.parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    base = Path(os.environ.get('KNOWNEXUS_STORAGE_ROOT') or root).resolve()
    data = base / "data"
    os.environ.setdefault('KNOWNEXUS_CONFIG_DIRECTORY', str(data))
    os.environ.setdefault("DATABASE_PATH", str(data / "knownexus.db"))
    os.environ.setdefault("RUNTIME_DATA_DIRECTORY", str(data))
    os.environ.setdefault("RUNTIME_LOG_DIRECTORY", str(base / "logs"))
    os.environ.setdefault("OBSERVABILITY_LOG_DIRECTORY", str(base / "logs" / "observability"))
    os.environ.setdefault("RAG_MODEL_CACHE_DIRECTORY", str(base / "model"))
    os.environ.setdefault('RAG_VECTOR_DATABASE_PATH', str(data / 'vector_db'))
    os.environ.setdefault('KNOWLEDGE_BASE_DIRECTORY', str(data / 'knowledge_base'))
    os.environ.setdefault('NOTE_EXPORT_DIRECTORY', str(data / '导出笔记'))
    os.environ.setdefault('HF_HOME', str(base / 'model' / '.hf'))
    os.environ.setdefault('HF_HUB_CACHE', str(base / 'model'))
    os.environ.setdefault('HF_XET_CACHE', str(base / 'model' / '.xet'))
    os.environ.setdefault('LEARNING_WHISPER_MODEL', str(root / 'model' / 'whisper-small'))
    os.environ.setdefault("LLM_API_KEY", "not-configured")


if __name__ == '__main__':
    multiprocessing.freeze_support()
    if '--knownexus-model-probe' in sys.argv:
        from study_help_agent.infrastructure.models.probe import main as probe_main
        probe_main(sys.argv[2:])
        raise SystemExit(0)

_configure_portable_data_paths()

from study_help_agent.app.main import app  # noqa: E402


def main() -> None:
    multiprocessing.freeze_support()
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
