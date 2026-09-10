import re
import os
import tempfile
from datetime import date, datetime
from pathlib import Path

from study_help_agent.capabilities.learning_notes.domain.models import GeneratedNote, SavedNote


class FileNoteRepository:
    """前端基础业务：笔记改、查、删"""
    def __init__(self, notes_directory: Path) -> None:
        self._directory = notes_directory.resolve()

    def _resolve(self, filename: str) -> Path:
        """文件名转化为文件的安全绝对路径"""
        if not filename or Path(filename).name != filename or not filename.endswith(".md"):
            raise FileNotFoundError(filename)
        path = (self._directory / filename).resolve()
        if path.parent != self._directory:
            raise FileNotFoundError(filename)
        return path

    def save(self, note: GeneratedNote) -> SavedNote:
        """保存笔记文件的具体实现"""
        self._directory.mkdir(parents=True, exist_ok=True)
        safe_title = re.sub(r'[\\/*?:"<>|]', "", note.title).strip() or "学习笔记"
        stem = f"{date.today().isoformat()}_{safe_title}"
        filename = f"{stem}.md"
        path = self._resolve(filename)
        sequence = 2
        while path.exists():
            filename = f"{stem}_{sequence}.md"
            path = self._resolve(filename)
            sequence += 1
        path.write_text(note.content, encoding="utf-8")
        return SavedNote(filename=filename, path=str(path), segments_count=len(note.segments))

    def list_notes(self) -> list[dict]:
        """列出所有笔记的具体实现"""
        if not self._directory.is_dir():
            return []
        result = []
        paths = sorted(
            self._directory.glob("*.md"),
            key=lambda item: (item.stat().st_mtime_ns, item.name),
            reverse=True,
        )
        for path in paths:
            stat = path.stat()
            result.append({
                "filename": path.name, "date": path.name[:10],
                "title": path.name[11:-3] if len(path.name) > 14 else path.stem,
                "size": stat.st_size, "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        return result

    def read(self, filename: str) -> str:
        """读取单篇笔记内容的具体实现"""
        path = self._resolve(filename)
        if not path.is_file():
            raise FileNotFoundError(filename)
        return path.read_text(encoding="utf-8")

    def update(self, filename: str, content: str) -> None:
        """更新笔记内容的具体实现"""
        path = self._resolve(filename)
        if not path.is_file():
            raise FileNotFoundError(filename)
        self._atomic_write(path, content)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        """先写同目录临时文件再原子替换，防止中断时损坏原笔记。"""
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def delete(self, filename: str) -> bool:
        """删除本地笔记文件的具体实现"""
        path = self._resolve(filename)
        if not path.is_file():
            return False
        path.unlink()
        return True
