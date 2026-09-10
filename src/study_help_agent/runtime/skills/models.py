"""定义 Skill 的运行时数据模型。

Skill 是可按需加载的过程知识，不直接执行代码。它声明适用场景、建议步骤和允许使用的
工具；Runtime 只把被加载 Skill 的完整说明放进当前 Loop 上下文。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    """保存一个 Skill 的元数据、正文指令和工具白名单。"""

    name: str
    description: str
    instructions: str
    allowed_tools: tuple[str, ...]
    source_path: Path

    def summary(self) -> dict[str, object]:
        """返回适合放入每轮 Prompt 的轻量目录项。"""

        return {
            "name": self.name,
            "description": self.description,
            "allowed_tools": list(self.allowed_tools),
        }

    def prompt_content(self) -> dict[str, object]:
        """返回 Skill 被加载后提供给决策器的完整内容。"""

        return {**self.summary(), "instructions": self.instructions}
