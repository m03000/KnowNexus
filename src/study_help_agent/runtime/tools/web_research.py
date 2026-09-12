"""Main Agent 专用的轻量联网研究工具。

这些工具只负责公开网页检索、正文读取和 GitHub 仓库概览，返回大文本时写入
Artifact，避免把整页内容长期塞进 Agent Prompt。所有 URL 都经过 SSRF 边界校验。
"""

from __future__ import annotations

import ipaddress
import re
import socket
from html import unescape
from typing import Any, Mapping
from urllib.parse import quote_plus, urlparse

import httpx

from .core import ToolDefinition, ToolExecutionContext, ToolResult


class MainWebResearchTools:
    """仅由 Main Profile 授权的公开网络能力。"""

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return (
            ToolDefinition("search_web", "搜索公开互联网。适合查找最新资料或候选来源；返回标题、链接和摘要。",
                           {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]}, self.search_web),
            ToolDefinition("read_web_page", "读取一个公开 HTTP/HTTPS 网页的主要文本；长正文保存为 Artifact。不能访问本机或私网地址。用户要求根据链接生成、整理、重写或保存笔记时禁止使用本工具，必须委派 Learning Agent。",
                           {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}, self.read_web_page),
            ToolDefinition("inspect_github_repository", "读取公开 GitHub 仓库的元数据、README 和文件树概览，用于先理解仓库再决定后续动作。",
                           {"type": "object", "properties": {"repository": {"type": "string"}, "include_tree": {"type": "boolean"}}, "required": ["repository"]}, self.inspect_github_repository),
        )

    def search_web(self, arguments: Mapping[str, Any], context: ToolExecutionContext) -> ToolResult:
        query = str(arguments["query"]).strip()
        limit = max(1, min(int(arguments.get("max_results", 5)), 10))
        if not query:
            raise ValueError("搜索词不能为空")
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        text = self._get(url)
        pattern = re.compile(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</', re.S)
        rows = []
        for href, title, snippet in pattern.findall(text)[:limit]:
            rows.append({"title": self._plain(title), "url": unescape(href), "snippet": self._plain(snippet)})
        return ToolResult(summary=f"搜索完成：{query}，获得 {len(rows)} 条公开结果", payload={"query": query, "results": rows})

    def read_web_page(self, arguments: Mapping[str, Any], context: ToolExecutionContext) -> ToolResult:
        url = self._public_url(str(arguments["url"]).strip())
        html = self._get(url)
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = self._plain(title_match.group(1)) if title_match else url
        body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
        body = self._plain(body)
        artifact = context.artifact_store.put(artifact_type="web_page", name=title,
            summary=f"网页正文：{title}（{len(body)} 字符）", content={"url": url, "title": title, "text": body})
        return ToolResult(summary=f"已读取网页：{title}", payload={"url": url, "title": title, "characters": len(body)}, artifact_ids=(artifact.artifact_id,))

    def inspect_github_repository(self, arguments: Mapping[str, Any], context: ToolExecutionContext) -> ToolResult:
        raw = str(arguments["repository"]).strip().rstrip("/")
        match = re.search(r"(?:github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?$", raw)
        if not match:
            raise ValueError("仓库必须是 owner/repo 或公开 GitHub URL")
        owner, repo = match.groups()
        base = f"https://api.github.com/repos/{owner}/{repo}"
        with httpx.Client(timeout=20, follow_redirects=True, headers={"Accept": "application/vnd.github+json", "User-Agent": "personal-agent"}) as client:
            metadata_response = client.get(base)
            metadata_response.raise_for_status()
            metadata = metadata_response.json()
            readme_response = client.get(f"{base}/readme", headers={"Accept": "application/vnd.github.raw+json"})
            readme = readme_response.text if readme_response.is_success else ""
            tree = []
            if bool(arguments.get("include_tree", True)):
                tree_response = client.get(f"{base}/git/trees/{metadata.get('default_branch', 'main')}?recursive=1")
                if tree_response.is_success:
                    tree = [item.get("path") for item in tree_response.json().get("tree", []) if item.get("type") == "blob"][:1000]
        content = {"repository": f"{owner}/{repo}", "description": metadata.get("description"), "language": metadata.get("language"),
                   "topics": metadata.get("topics", []), "stars": metadata.get("stargazers_count", 0), "readme": readme, "files": tree}
        artifact = context.artifact_store.put(artifact_type="github_repository", name=f"{owner}/{repo}",
            summary=f"GitHub 仓库概览：{owner}/{repo}，{len(tree)} 个文件路径", content=content)
        return ToolResult(summary=f"已读取 GitHub 仓库 {owner}/{repo}", payload={k: content[k] for k in ("repository", "description", "language", "topics", "stars")}, artifact_ids=(artifact.artifact_id,))

    def _get(self, url: str) -> str:
        safe = self._public_url(url)
        with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 PersonalKnowledgeAgent/1.0"}) as client:
            response = client.get(safe)
            response.raise_for_status()
            self._public_url(str(response.url))
            if len(response.content) > 2 * 1024 * 1024:
                raise ValueError("网页超过 2 MB 安全读取上限")
            return response.text

    @staticmethod
    def _plain(value: str) -> str:
        return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()

    @staticmethod
    def _public_url(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("仅允许公开 HTTP/HTTPS URL")
        for info in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)):
            ip = ipaddress.ip_address(info[4][0])
            if not ip.is_global:
                raise PermissionError("禁止访问本机、私网或保留网络地址")
        return url
