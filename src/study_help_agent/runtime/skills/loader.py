"""从项目中的 SKILL.md 文件加载过程知识。

加载器使用极小的 front matter 解析规则，避免为了几个字符串字段引入 YAML 依赖。
正文保持 Markdown 原样，便于人类阅读、版本控制和 LLM 消费。
"""

from __future__ import annotations

from pathlib import Path

from study_help_agent.runtime.skills.models import SkillDefinition


class FileSystemSkillLoader:
    """递归发现并解析指定根目录下的 SKILL.md。"""

    def __init__(self, *, root: Path) -> None:
        """保存解析后的 Skill 根目录。"""

        self._root = Path(root).resolve()

    def load_all(self) -> tuple[SkillDefinition, ...]:
        """按路径排序加载全部 Skill，保证启动结果稳定。"""

        if not self._root.exists():
            return ()
        return tuple(self.load(path) for path in sorted(self._root.rglob("SKILL.md")))

    def load(self, path: Path) -> SkillDefinition:
        """解析一个带简单 front matter 的 SKILL.md。"""

        actual = Path(path).resolve()
        try:
            actual.relative_to(self._root)
        except ValueError as error:
            raise ValueError("Skill file must stay inside skill root") from error
        text = actual.read_text(encoding="utf-8")
        metadata, instructions = self._split(text)
        name = metadata.get("name", "").strip()
        description = metadata.get("description", "").strip()
        if not name or not description or not instructions.strip():
            raise ValueError(f"Invalid skill document: {actual}")
        allowed = tuple(item.strip() for item in metadata.get("allowed_tools", "").split(",") if item.strip())
        return SkillDefinition(name=name, description=description, instructions=instructions.strip(), allowed_tools=allowed, source_path=actual)

    @staticmethod
    def _split(text: str) -> tuple[dict[str, str], str]:
        """分离 front matter 和 Markdown 正文。"""

        lines = text.lstrip("\ufeff").splitlines()
        if not lines or lines[0].strip() != "---":
            raise ValueError("SKILL.md must start with --- front matter")
        try:
            end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
        except StopIteration as error:
            raise ValueError("SKILL.md front matter is not closed") from error
        metadata: dict[str, str] = {}
        for line in lines[1:end]:
            if not line.strip():
                continue
            key, separator, value = line.partition(":")
            if not separator:
                raise ValueError(f"Invalid skill metadata line: {line}")
            metadata[key.strip()] = value.strip()
        return metadata, "\n".join(lines[end + 1 :])
