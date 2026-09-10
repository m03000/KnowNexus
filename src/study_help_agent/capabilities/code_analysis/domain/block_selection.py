from dataclasses import dataclass
from enum import StrEnum

from study_help_agent.capabilities.code_analysis.domain.source_analysis import ParsedCodeBlock


def build_block_id(block: ParsedCodeBlock) -> str:
    """用类型、父类、名称和行号生成一次源码快照内稳定的代码块标识。"""

    return ":".join((
        block.block_type.value,
        block.parent_class,
        block.name,
        str(block.line_start),
        str(block.line_end),
    ))


class BlockAnalysisLevel(StrEnum):
    DETAILED = "detailed"
    NORMAL = "normal"
    TEMPLATE = "template"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class BlockSelection:
    block_id: str
    score: int
    level: BlockAnalysisLevel
    reasons: tuple[str, ...]


class CodeBlockImportanceScorer:
    SIMPLE_METHODS = {
        "__str__",
        "__repr__",
        "__len__",
        "__iter__",
    }

    def score(self, block) -> BlockSelection:
        score = 0
        reasons = []

        lines = block.line_end - block.line_start + 1

        if block.name in {"main", "run", "invoke", "execute", "build", "create"}:
            score += 3
            reasons.append("疑似执行入口")

        if block.block_type.value in {"function", "method"}:
            score += 1

        if lines >= 30:
            score += 2
            reasons.append("代码块较复杂")

        if lines >= 80:
            score += 2
            reasons.append("大型代码块")

        if "raise " in block.code:
            score += 1
            reasons.append("包含异常边界")

        if any(word in block.code for word in ("await ", "yield ", "with ", "match ")):
            score += 1
            reasons.append("包含特殊控制流")

        if block.name.startswith("get_") and lines <= 5:
            score -= 2
            reasons.append("简单读取方法")

        if block.name in self.SIMPLE_METHODS and lines <= 8:
            score -= 2
            reasons.append("简单协议方法")

        if block.block_type.value == "block" and lines <= 3:
            score -= 2
            reasons.append("短顶层语句")

        if score >= 4:
            level = BlockAnalysisLevel.DETAILED
        elif score >= 1:
            level = BlockAnalysisLevel.NORMAL
        elif score >= -1:
            level = BlockAnalysisLevel.TEMPLATE
        else:
            level = BlockAnalysisLevel.SKIP

        return BlockSelection(
            block_id=build_block_id(block),
            score=score,
            level=level,
            reasons=tuple(reasons),
        )
