"""提供 Skill 注册、查找和目录查询能力。"""

from __future__ import annotations

from collections.abc import Iterable

from study_help_agent.runtime.skills.models import SkillDefinition


class SkillRegistry:
    """集中保存已发现 Skill，并阻止空名称和重复注册。"""

    def __init__(self) -> None:
        """初始化空 Skill 字典。"""

        self._skills: dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition) -> None:
        """注册一个 Skill。"""

        name = skill.name.strip()
        if not name:
            raise ValueError("Skill name cannot be empty")
        if name in self._skills:
            raise ValueError(f"Skill already registered: {name}")
        self._skills[name] = skill

    def register_many(self, skills: Iterable[SkillDefinition]) -> None:
        """批量注册 Skill。"""

        for skill in skills:
            self.register(skill)

    def get(self, name: str) -> SkillDefinition:
        """按名称读取 Skill，未知名称抛出明确异常。"""

        try:
            return self._skills[name]
        except KeyError as error:
            raise KeyError(f"Skill not registered: {name}") from error

    def summaries(self) -> tuple[dict[str, object], ...]:
        """返回全部 Skill 的轻量目录。"""

        return tuple(skill.summary() for skill in self._skills.values())

    def loaded(self, names: tuple[str, ...]) -> tuple[dict[str, object], ...]:
        """返回当前运行已经加载的完整 Skill 内容。"""

        return tuple(self.get(name).prompt_content() for name in names)

    def names(self) -> tuple[str, ...]:
        """返回稳定的 Skill 名称集合。"""

        return tuple(self._skills)

    def select(self, names: tuple[str, ...]) -> "SkillRegistry":
        """创建只暴露指定 Skill 的最小权限注册表。"""

        selected = SkillRegistry()
        selected.register_many(self.get(name) for name in names)
        return selected
