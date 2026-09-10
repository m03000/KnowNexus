"""源码文件公共模型。"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceFile:
    """项目中的一个源码文件。"""

    absolute_path: Path
    relative_path: str
    language: str

    @property
    def name(self) -> str:
        """返回文件名。"""

        return self.absolute_path.name

    @property
    def suffix(self) -> str:
        """返回小写文件扩展名。"""

        return self.absolute_path.suffix.lower()