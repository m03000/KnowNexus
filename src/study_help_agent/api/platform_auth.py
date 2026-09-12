"""Local-only import and lifecycle management for platform video cookies."""
from __future__ import annotations

from datetime import UTC, datetime
from http.cookiejar import LoadError, MozillaCookieJar
from pathlib import Path
import os
import shutil
import tempfile

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/settings/platform-auth", tags=["platform-auth"])
MAX_COOKIE_FILE_BYTES = 2 * 1024 * 1024


class CookieImportPayload(BaseModel):
    source_path: str = Field(min_length=1, max_length=4096)


def _cookie_path(request: Request) -> Path:
    return request.app.state.container.settings.runtime_data_directory / "platform_auth" / "cookies.txt"


def _inspect(path: Path) -> dict:
    if not path.is_file():
        return {"configured": False, "path": str(path), "cookie_count": 0, "domains": [], "message": "尚未导入平台 Cookie"}
    try:
        if path.stat().st_size > MAX_COOKIE_FILE_BYTES:
            raise ValueError("Cookie 文件超过 2 MB 限制")
        with path.open("r", encoding="utf-8-sig", errors="strict") as stream:
            first_line = stream.readline().strip()
        if first_line not in {"# HTTP Cookie File", "# Netscape HTTP Cookie File"}:
            raise ValueError("文件不是 Netscape cookies.txt 格式")
        jar = MozillaCookieJar(str(path))
        jar.load(ignore_discard=True, ignore_expires=True)
        cookies = list(jar)
        if not cookies:
            raise ValueError("Cookie 文件中没有可用记录")
        now = datetime.now(UTC).timestamp()
        live = [cookie for cookie in cookies if cookie.expires is None or cookie.expires > now]
        domains = sorted({cookie.domain.lstrip(".") for cookie in live})
        return {"configured": True, "path": str(path), "cookie_count": len(live),
                "domains": domains[:8], "updated_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                "message": f"已载入 {len(live)} 条未过期 Cookie"}
    except (OSError, UnicodeError, LoadError, ValueError) as exc:
        return {"configured": False, "path": str(path), "cookie_count": 0, "domains": [],
                "message": f"Cookie 文件不可用：{exc}"}


@router.get("")
def get_platform_auth(request: Request) -> dict:
    return _inspect(_cookie_path(request))


@router.post("/import")
def import_platform_auth(payload: CookieImportPayload, request: Request) -> dict:
    source = Path(payload.source_path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".txt":
        raise HTTPException(status_code=400, detail="请选择有效的 cookies.txt 文件")
    inspected = _inspect(source)
    if not inspected["configured"]:
        raise HTTPException(status_code=400, detail=inspected["message"])
    target = _cookie_path(request)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix="cookies-", suffix=".tmp", delete=False) as temporary:
            temporary_name = temporary.name
            with source.open("rb") as stream:
                shutil.copyfileobj(stream, temporary)
        os.replace(temporary_name, target)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return _inspect(target)


@router.delete("")
def clear_platform_auth(request: Request) -> dict:
    _cookie_path(request).unlink(missing_ok=True)
    return _inspect(_cookie_path(request))
