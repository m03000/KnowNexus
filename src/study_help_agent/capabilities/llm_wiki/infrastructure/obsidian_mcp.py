"""Obsidian Vault MCP publishing with local Wiki kept as the durable fallback."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ObsidianWikiConfig:
    enabled: bool = False
    vault_path: str = ""
    wiki_folder: str = "AgentWiki"
    package: str = "obsidian-mcp@2"
    verified: bool = False
    vaults: list[dict[str, Any]] = field(default_factory=list)
    active_vault_id: str = ""


class ObsidianWikiConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> ObsidianWikiConfig:
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
            config = ObsidianWikiConfig(**values)
            if not config.vaults and config.vault_path:
                config.active_vault_id = config.active_vault_id or "default"
                config.vaults = [{"id": config.active_vault_id, "name": Path(config.vault_path).name or "默认 Vault", "path": config.vault_path, "wiki_folder": config.wiki_folder, "verified": config.verified}]
            active = next((item for item in config.vaults if item.get("id") == config.active_vault_id), None)
            if active:
                config.vault_path = str(active.get("path") or "")
                config.wiki_folder = str(active.get("wiki_folder") or "AgentWiki")
                config.verified = bool(active.get("verified"))
            return config
        except (OSError, ValueError, TypeError):
            return ObsidianWikiConfig()

    def save(self, config: ObsidianWikiConfig) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)


class StdioMcpClient:
    """Small newline-delimited MCP client; one short-lived process per operation."""
    def __init__(self, config: ObsidianWikiConfig) -> None:
        self.config = config

    def _start(self):
        vault = str(Path(self.config.vault_path).expanduser().resolve())
        npx = shutil.which("npx.cmd" if os.name == "nt" else "npx")
        if not npx:
            raise RuntimeError("未检测到 npx；连接测试不会自动下载 MCP，请先手动安装")
        command = [npx, "--offline", "--yes", self.config.package,
                   "serve", "--vault", f"notes={vault}"]
        environment = {**os.environ, "npm_config_offline": "true", "npm_config_prefer_offline": "true"}
        return subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    @staticmethod
    def _send(process, payload: dict) -> None:
        assert process.stdin is not None
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()

    @staticmethod
    def _receive(process, request_id: int) -> dict:
        assert process.stdout is not None
        while True:
            line = process.stdout.readline()
            if not line:
                error = process.stderr.read() if process.stderr else ""
                raise RuntimeError(error.strip() or "Obsidian MCP exited without a response")
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") == request_id:
                if message.get("error"):
                    raise RuntimeError(str(message["error"]))
                return message.get("result") or {}

    def tools(self) -> list[dict[str, Any]]:
        process = self._start()
        try:
            self._send(process, {"jsonrpc":"2.0","id":1,"method":"initialize","params":{
                "protocolVersion":"2024-11-05","capabilities":{},
                "clientInfo":{"name":"AgentForge","version":"1"}}})
            self._receive(process, 1)
            self._send(process, {"jsonrpc":"2.0","method":"notifications/initialized","params":{}})
            self._send(process, {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
            return list(self._receive(process, 2).get("tools") or [])
        finally:
            process.terminate()
            try: process.wait(timeout=2)
            except subprocess.TimeoutExpired: process.kill()

    def call(self, name: str, arguments: dict[str, Any]) -> dict:
        process = self._start()
        try:
            self._send(process, {"jsonrpc":"2.0","id":1,"method":"initialize","params":{
                "protocolVersion":"2024-11-05","capabilities":{},
                "clientInfo":{"name":"AgentForge","version":"1"}}})
            self._receive(process, 1)
            self._send(process, {"jsonrpc":"2.0","method":"notifications/initialized","params":{}})
            self._send(process, {"jsonrpc":"2.0","id":3,"method":"tools/call",
                "params":{"name":name,"arguments":arguments}})
            return self._receive(process, 3)
        finally:
            process.terminate()
            try: process.wait(timeout=2)
            except subprocess.TimeoutExpired: process.kill()


class ObsidianMcpPublisher:
    def __init__(self, config_path: Path) -> None:
        self.store = ObsidianWikiConfigStore(config_path)

    def status(self, *, probe: bool = False) -> dict:
        config = self.store.load()
        result = {**asdict(config), "configured": bool(config.vault_path),
                  "connected": bool(config.enabled and config.vault_path and config.verified),
                  "tool_count": 0, "tools": [], "message": "尚未启用"}
        if not config.enabled or not config.vault_path:
            return result
        vault = Path(config.vault_path).expanduser()
        if not vault.is_dir():
            return {**result, "message": "Vault 路径不存在"}
        if not probe:
            return {**result, "message": "连接已验证" if config.verified else "已配置，等待连接测试"}
        try:
            tools = StdioMcpClient(config).tools()
            names = [str(item.get("name") or "") for item in tools]
            config.verified = True
            for item in config.vaults:
                if item.get("id") == config.active_vault_id:
                    item["verified"] = True
            self.store.save(config)
            return {**result, "connected": True, "tool_count": len(names), "tools": names,
                    "message": "Obsidian MCP 连接正常"}
        except Exception as exc:
            return {**result, "message": str(exc)}

    def publish(self, pages: list[dict]) -> None:
        config = self.store.load()
        if not config.enabled or not config.vault_path:
            return
        client = StdioMcpClient(config)
        tools = client.tools()
        names = {str(item.get("name")): item for item in tools}
        tool = next((name for name in ("obsidian_upsert_note", "obsidian_create_note", "write_file") if name in names), "")
        if not tool:
            raise RuntimeError("Obsidian MCP 未提供可用的页面写入工具")
        schema = (names[tool].get("inputSchema") or {}).get("properties") or {}
        for page in pages:
            if page.get("status") in {"deleted", "archived"} or not page.get("slug"):
                continue
            folder = {"topic":"10 Topics", "concept":"20 Concepts", "synthesis":"30 Syntheses", "source":"40 Sources"}.get(str(page.get("page_type")), "40 Sources")
            path = f"{config.wiki_folder.strip('/')}/{folder}/{page['slug']}.md"
            body = re.sub(r"\[([^]]+)\]\(wiki://(?:page|slug)/[^)]+\)", r"[[\1]]", str(page.get("body_markdown") or ""))
            frontmatter = ("---\n" f"wiki_id: \"{page.get('page_id','')}\"\n" f"page_type: {page.get('page_type','source')}\n" "managed_by: AgentForge\n" "---\n\n")
            args: dict[str, Any] = {}
            for key in schema:
                low = key.casefold()
                if low in {"path", "file_path", "filepath"}: args[key] = path
                elif low in {"content", "body", "markdown"}: args[key] = frontmatter + body
                elif low == "create_directories": args[key] = True
                elif low in {"vault", "vault_id", "vaultid"}: args[key] = "notes"
            try:
                client.call(tool, args)
            except RuntimeError:
                edit_tool = names.get("obsidian_edit_note")
                if not edit_tool:
                    raise
                edit_args: dict[str, Any] = {}
                properties = (edit_tool.get("inputSchema") or {}).get("properties") or {}
                for key in properties:
                    low = key.casefold()
                    if low in {"path", "file_path", "filepath"}: edit_args[key] = path
                    elif low in {"content", "body", "markdown", "text"}: edit_args[key] = frontmatter + body
                    elif low in {"vault", "vault_id", "vaultid"}: edit_args[key] = "notes"
                    elif low in {"operation", "mode"}: edit_args[key] = "replace"
                client.call("obsidian_edit_note", edit_args)
