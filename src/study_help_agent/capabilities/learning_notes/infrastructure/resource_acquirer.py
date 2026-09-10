"""本地文件与外部平台资源的安全获取适配器。

本地文件会复制到受控目录；普通文件链接使用有体积上限的 HTTP 下载；页面型视频链接
使用延迟加载的 yt-dlp。这里不解析正文，只建立可追踪的原始资源。
"""

from __future__ import annotations

import hashlib
import ipaddress
import mimetypes
import shutil
import socket
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from study_help_agent.capabilities.learning_notes.domain import AcquiredResource


class _SafeRedirectHandler(HTTPRedirectHandler):
    """在真正跟随 HTTP 重定向前重新执行目标地址校验。"""

    def __init__(self, validator) -> None:
        super().__init__()
        self._validator = validator

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self._validator(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ManagedLearningResourceAcquirer:
    """将用户来源转换为运行目录内的受控文件。"""

    DIRECT_EXTENSIONS = {
        ".txt", ".md", ".markdown", ".json", ".html", ".htm",
        ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".webp", ".bmp",
        ".tif", ".tiff", ".mp3", ".wav", ".m4a", ".aac", ".flac",
        ".mp4", ".mov", ".mkv", ".webm", ".avi",
    }
    MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".mp3", ".m4a", ".wav"}
    SUBTITLE_EXTENSIONS = {".vtt", ".srt", ".ass", ".ssa"}

    def __init__(
        self,
        *,
        storage_directory: Path,
        allowed_roots: list[Path],
        max_bytes: int,
        video_cookie_browser: str = "",
    ) -> None:
        self._storage = storage_directory.resolve()
        self._allowed_roots = [item.expanduser().resolve() for item in allowed_roots]
        self._max_bytes = max_bytes
        self._video_cookie_browser = video_cookie_browser.strip().lower()

    def acquire(self, source: str) -> AcquiredResource:
        """根据 URI scheme 选择本地复制、直接下载或平台下载。"""

        parsed = urlparse(source)
        if parsed.scheme.lower() in {"http", "https"}:
            self._validate_public_url(source)
            suffix = Path(unquote(parsed.path)).suffix.lower()
            if suffix in self.DIRECT_EXTENSIONS:
                path, metadata = self._download_direct(source)
            else:
                path, metadata = self._download_platform(source)
            source_type = "external_url"
        else:
            path, metadata = self._copy_local(source)
            source_type = "local_file"
        return self._to_resource(
            path=path,
            source=source,
            source_type=source_type,
            metadata=metadata,
        )

    def release(self, resource: AcquiredResource) -> bool:
        """安全删除本适配器创建的资源副本及空目录。"""

        path = Path(resource.local_path).resolve()
        self._storage.mkdir(parents=True, exist_ok=True)
        if not path.is_relative_to(self._storage) or not path.is_file():
            return False
        sidecars = resource.metadata.get("subtitle_paths", [])
        for item in sidecars if isinstance(sidecars, list) else []:
            candidate = Path(str(item)).resolve()
            if candidate.is_relative_to(self._storage) and candidate.is_file():
                candidate.unlink()
        path.unlink()
        parent = path.parent
        if parent != self._storage and not any(parent.iterdir()):
            parent.rmdir()
        return True

    def _copy_local(self, source: str) -> tuple[Path, dict]:
        """校验允许根目录与体积后复制本地文件。"""

        path = Path(source).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"资源路径不是文件：{source}")
        if self._allowed_roots and not any(
            path.is_relative_to(root) for root in self._allowed_roots
        ):
            raise PermissionError(f"资源文件不在允许访问的目录中：{source}")
        self._validate_size(path.stat().st_size)
        target_dir = self._new_target_directory(source)
        target = target_dir / self._safe_filename(path.name)
        shutil.copy2(path, target)
        return target, {"original_path": str(path)}

    def _download_direct(self, source: str) -> tuple[Path, dict]:
        """流式下载普通文档、图片、音频或直接视频链接。"""

        target_dir = self._new_target_directory(source)
        opener = build_opener(_SafeRedirectHandler(self._validate_public_url))
        request = Request(source, headers={"User-Agent": "StudyHelpAgent/1.0"})
        with opener.open(request, timeout=60) as response:
            final_url = response.geturl()
            self._validate_public_url(final_url)
            declared = response.headers.get("Content-Length")
            if declared:
                self._validate_size(int(declared))
            raw_name = Path(unquote(urlparse(final_url).path)).name or "download"
            content_type = response.headers.get_content_type()
            if not Path(raw_name).suffix:
                raw_name += mimetypes.guess_extension(content_type) or ".bin"
            target = target_dir / self._safe_filename(raw_name)
            total = 0
            with target.open("wb") as stream:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    self._validate_size(total)
                    stream.write(chunk)
        return target, {"final_url": final_url, "content_type": content_type}

    def _download_platform(self, source: str) -> tuple[Path, dict]:
        """使用 yt-dlp 获取抖音等受支持平台的视频，并保留少量安全元数据。"""

        try:
            from yt_dlp import YoutubeDL
        except ImportError as error:
            raise RuntimeError(
                "平台视频获取需要安装可选依赖：pip install -e .[learning-media]"
            ) from error
        target_dir = self._new_target_directory(source)
        options = {
            "format": "bestvideo*+bestaudio/best",
            "outtmpl": str(target_dir / "%(id)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "max_filesize": self._max_bytes,
            # 字幕优先：平台提供人工或自动字幕时一并保存，后续可跳过 Whisper。
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["zh-Hans", "zh-CN", "zh", "ai-zh", "en"],
            "subtitlesformat": "vtt/srt/best",
        }
        if self._video_cookie_browser:
            options["cookiesfrombrowser"] = (self._video_cookie_browser,)
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(source, download=True)
            prepared = Path(downloader.prepare_filename(info))
        candidates = [
            item for item in target_dir.iterdir()
            if item.is_file() and item.suffix.lower() in self.MEDIA_EXTENSIONS
        ]
        if prepared.is_file():
            path = prepared
        elif candidates:
            path = max(candidates, key=lambda item: item.stat().st_mtime_ns)
        else:
            raise FileNotFoundError("平台解析成功但没有找到下载后的媒体文件")
        self._validate_size(path.stat().st_size)
        subtitle_paths = [
            str(item.resolve())
            for item in sorted(target_dir.iterdir())
            if item.is_file() and item.suffix.lower() in self.SUBTITLE_EXTENSIONS
        ]
        return path, {
            "platform": str(info.get("extractor_key") or info.get("extractor") or ""),
            "title": str(info.get("title") or ""),
            "uploader": str(info.get("uploader") or ""),
            "duration": info.get("duration"),
            "webpage_url": str(info.get("webpage_url") or source),
            "subtitle_paths": subtitle_paths,
            "subtitle_available": bool(subtitle_paths),
        }

    @staticmethod
    def _safe_filename(name: str) -> str:
        """移除 Windows 非法字符并限制文件名长度。"""

        forbidden = '<>:"/\\|?*'
        cleaned = "".join("_" if char in forbidden else char for char in name).strip(" .")
        return (cleaned or "resource.bin")[:180]

    def _new_target_directory(self, source: str) -> Path:
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]
        target = self._storage / digest
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _validate_size(self, size: int) -> None:
        if size > self._max_bytes:
            raise ValueError(
                f"资源大小 {size} 字节超过允许上限 {self._max_bytes} 字节"
            )

    @staticmethod
    def _validate_public_url(url: str) -> None:
        """拒绝非 HTTP 协议以及解析到本机、私网或保留地址的 URL。"""

        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("外部资源只允许使用 http 或 https URL")
        try:
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
        except socket.gaierror as error:
            raise ValueError(f"无法解析外部资源域名：{parsed.hostname}") from error
        # Clash/Mihomo 的 fake-ip 模式会把公网域名映射到 198.18.0.0/15。
        # 该地址只交给本机代理继续转发，并不是服务端主动访问的内网目标。
        proxy_fake_ip_network = ipaddress.ip_network("198.18.0.0/15")
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if ip in proxy_fake_ip_network:
                continue
            if not ip.is_global:
                raise PermissionError("禁止访问本机、私网、链路本地或保留网络地址")

    @staticmethod
    def _to_resource(
        *, path: Path, source: str, source_type: str, metadata: dict
    ) -> AcquiredResource:
        size = path.stat().st_size
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return AcquiredResource(
            resource_id=f"resource_{digest.hexdigest()[:24]}",
            local_path=str(path.resolve()),
            source_uri=source,
            source_type=source_type,
            media_type=media_type,
            file_name=path.name,
            size_bytes=size,
            metadata=metadata,
        )
