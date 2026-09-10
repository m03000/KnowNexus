"""Obsidian-backed Wiki integration settings."""
from pathlib import Path
import tempfile
import uuid
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from study_help_agent.capabilities.llm_wiki.infrastructure.obsidian_mcp import (
    ObsidianWikiConfig, ObsidianMcpPublisher, StdioMcpClient,
)

router = APIRouter(prefix="/api/settings/obsidian-wiki", tags=["Obsidian Wiki"])

class ObsidianSettingsPayload(BaseModel):
    enabled: bool = False
    vault_path: str = Field(default="", max_length=1000)
    wiki_folder: str = Field(default="AgentWiki", min_length=1, max_length=200)
    vault_id: str = Field(default="", max_length=100)
    vault_name: str = Field(default="", max_length=120)

def _publisher(request: Request) -> ObsidianMcpPublisher:
    return ObsidianMcpPublisher(request.app.state.container.settings.runtime_data_directory / "obsidian_wiki.json")

def _status(request: Request, *, probe: bool = False) -> dict:
    result = _publisher(request).status(probe=probe)
    wiki_root = (request.app.state.container.settings.runtime_data_directory / "wiki").resolve()
    result["builtin_wiki"] = {"name": "内置 Wiki", "directory": "LLM Wiki", "path": str(wiki_root)}
    return result

@router.get("")
def get_settings(request: Request):
    return _status(request)

@router.put("")
def save_settings(payload: ObsidianSettingsPayload, request: Request):
    vault = Path(payload.vault_path).expanduser()
    if payload.enabled:
        if not str(payload.vault_path).strip():
            raise HTTPException(400, "请填写 Wiki 路径")
        try:
            vault.mkdir(parents=True, exist_ok=True)
            (vault / ".obsidian").mkdir(exist_ok=True)
            (vault / payload.wiki_folder.strip()).mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise HTTPException(400, f"无法创建 Wiki：{error}") from error
    publisher = _publisher(request)
    previous = publisher.store.load()
    vault_id = payload.vault_id.strip() or uuid.uuid4().hex[:12]
    verified = previous.verified and previous.vault_path == payload.vault_path.strip()
    vault = {"id": vault_id, "name": payload.vault_name.strip() or Path(payload.vault_path).name or "Vault",
             "path": payload.vault_path.strip(), "wiki_folder": payload.wiki_folder.strip(), "verified": verified}
    vaults = [item for item in previous.vaults if item.get("id") != vault_id] + [vault]
    publisher.store.save(ObsidianWikiConfig(enabled=payload.enabled, vault_path=vault["path"],
        wiki_folder=vault["wiki_folder"], verified=verified, vaults=vaults, active_vault_id=vault_id))
    return _status(request)

@router.post("/vaults/{vault_id}/activate")
def activate_vault(vault_id: str, request: Request):
    publisher = _publisher(request)
    config = publisher.store.load()
    vault = next((item for item in config.vaults if item.get("id") == vault_id), None)
    if vault is None:
        raise HTTPException(404, "Vault 不存在")
    config.active_vault_id = vault_id
    config.vault_path = str(vault.get("path") or "")
    config.wiki_folder = str(vault.get("wiki_folder") or "AgentWiki")
    config.verified = bool(vault.get("verified"))
    publisher.store.save(config)
    return _status(request, probe=config.enabled)

@router.post("/test")
def test_connection(request: Request):
    result = _status(request, probe=True)
    if not result["connected"]:
        raise HTTPException(400, result["message"])
    return result

@router.post("/test-runtime")
def test_runtime():
    """Download/launch the MCP package against a disposable Vault."""
    try:
        with tempfile.TemporaryDirectory(prefix="obsidian-mcp-test-") as directory:
            Path(directory, ".obsidian").mkdir()
            tools = StdioMcpClient(ObsidianWikiConfig(enabled=True, vault_path=directory)).tools()
    except (OSError, RuntimeError) as error:
        raise HTTPException(400, f"Obsidian MCP 不可用：{error}") from error
    return {"available": True, "tool_count": len(tools), "tools": [item.get("name", "") for item in tools]}
