"""按业务域安全清理本地测试数据；执行前请停止后端、MCP 和 Watcher。"""
from __future__ import annotations
import argparse, os, shutil, sqlite3
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = (PROJECT_ROOT / "data" / "desktop" / "data").resolve()
DATABASE_PATH = DATA_ROOT / "study_help.db"
DOMAIN_TABLES = {
    "memory": ("memory_processing_leases", "conversation_turns", "memory_relations", "memory_sources", "memory_entities", "memory_points_fts", "memory_points", "memories", "messages_fts", "messages", "conversations", "watcher_monitor_buckets", "watcher_monitor_sessions"),
    "notes": ("note_point_links", "knowledge_points", "note_library_entries", "library_documents", "library_folders", "wiki_page_versions", "wiki_page_sources", "wiki_links", "wiki_aliases", "wiki_build_queue", "wiki_builds", "wiki_pages_fts", "wiki_pages", "wiki_sources", "knowledge_chunks_fts", "knowledge_chunks", "ingestion_outbox", "knowledge_assets"),
    "projects": ("code_explainer_blocks", "code_explainer_source_files", "code_explainer_projects"),
}
DOMAIN_DIRECTORIES = {
    "memory": ("external_watcher_checkpoints", "external_watcher_spools"),
    "notes": ("notes", "learning_resources", "sources", "wiki", "library_documents"),
    "projects": (),
}
DOMAIN_COLLECTIONS = {"memory": ("user_memory",), "notes": ("personal_knowledge",), "projects": ("project_code",)}

@dataclass(slots=True)
class CleanupSummary:
    files: int = 0; directories: int = 0; bytes: int = 0; rows: int = 0; collections: int = 0
    def add(self, other: "CleanupSummary") -> None:
        for name in ("files", "directories", "bytes", "rows", "collections"):
            setattr(self, name, getattr(self, name) + getattr(other, name))

def _safe(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == DATA_ROOT or DATA_ROOT not in resolved.parents:
        raise RuntimeError(f"拒绝操作数据目录之外的路径：{resolved}")
    return resolved

def _measure(path: Path) -> CleanupSummary:
    if path.is_file() or path.is_symlink():
        return CleanupSummary(files=1, bytes=path.stat().st_size if path.exists() else 0)
    result = CleanupSummary(directories=1)
    if path.is_dir():
        for child in path.iterdir(): result.add(_measure(child))
    return result

def _clear_sqlite(scope: str, dry_run: bool) -> CleanupSummary:
    result = CleanupSummary()
    if not DATABASE_PATH.exists(): return result
    connection = sqlite3.connect(DATABASE_PATH, timeout=5)
    try:
        existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in DOMAIN_TABLES[scope]:
            if table not in existing: continue
            count = int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            result.rows += count
            if not dry_run: connection.execute(f'DELETE FROM "{table}"')
        connection.rollback() if dry_run else connection.commit()
        if not dry_run: connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally: connection.close()
    return result

def _clear_vectors(scope: str, dry_run: bool) -> CleanupSummary:
    vector_path = DATA_ROOT / "vector_db"
    if not vector_path.exists(): return CleanupSummary()
    from qdrant_client import QdrantClient
    client = QdrantClient(path=str(vector_path))
    try:
        existing = {item.name for item in client.get_collections().collections}
        targets = [name for name in DOMAIN_COLLECTIONS[scope] if name in existing]
        if not dry_run:
            for name in targets: client.delete_collection(name)
        return CleanupSummary(collections=len(targets))
    finally: client.close()

def _clear_directories(scope: str, dry_run: bool) -> CleanupSummary:
    result = CleanupSummary()
    for name in DOMAIN_DIRECTORIES[scope]:
        target = _safe(DATA_ROOT / name)
        if not target.exists(): continue
        result.add(_measure(target))
        if not dry_run:
            shutil.rmtree(target) if target.is_dir() else target.unlink(missing_ok=True)
    return result

def _clear_memory_user_state(dry_run: bool) -> CleanupSummary:
    result = CleanupSummary(); local = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
    paths = (Path(os.getenv("PERSONAL_AGENT_CODEX_CHECKPOINT", "") or local / "personal_agent" / "codex_watcher_checkpoint.db"), Path(os.getenv("PERSONAL_AGENT_CAPTURE_SPOOL", "") or local / "personal_agent" / "codex_capture_spool.db"))
    for path in paths:
        if path.exists():
            result.add(_measure(path))
            if not dry_run: path.unlink(missing_ok=True)
    return result

def reset_domain_data(scope: str, *, dry_run: bool = False) -> CleanupSummary:
    if scope not in DOMAIN_TABLES: raise ValueError(f"未知清理范围：{scope}")
    DATA_ROOT.mkdir(parents=True, exist_ok=True); total = CleanupSummary()
    total.add(_clear_sqlite(scope, dry_run)); total.add(_clear_vectors(scope, dry_run)); total.add(_clear_directories(scope, dry_run))
    if scope == "memory": total.add(_clear_memory_user_state(dry_run))
    return total

def reset_project_data(*, dry_run: bool = False) -> CleanupSummary:
    total = CleanupSummary()
    for scope in ("memory", "notes", "projects"): total.add(reset_domain_data(scope, dry_run=dry_run))
    return total

def main() -> int:
    parser = argparse.ArgumentParser(description="按业务域清理 Personal Agent 测试数据")
    parser.add_argument("--scope", choices=("memory", "notes", "projects", "all"), default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try: result = reset_project_data(dry_run=args.dry_run) if args.scope == "all" else reset_domain_data(args.scope, dry_run=args.dry_run)
    except (PermissionError, sqlite3.OperationalError) as error:
        print(f"清理失败，请先停止后端、MCP 和 Watcher：{error}"); return 2
    label = {"memory":"记忆数据", "notes":"笔记数据", "projects":"项目数据", "all":"全部业务数据"}[args.scope]
    print(f"{label}{'预计清理' if args.dry_run else '清理完成'}：{result.rows} 行、{result.collections} 个向量集合、{result.files} 个文件、{result.directories} 个目录。")
    print("已保留模型、监听器配置、Obsidian 配置、外部源文件和 Vault。")
    return 0

if __name__ == "__main__": raise SystemExit(main())
