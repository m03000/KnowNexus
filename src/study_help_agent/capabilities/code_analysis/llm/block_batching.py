from dataclasses import dataclass

from study_help_agent.capabilities.code_analysis.domain.source_analysis import (
    ParsedCodeBlock,
)


@dataclass(frozen=True, slots=True)
class CodeBlockBatch:
    blocks: tuple[ParsedCodeBlock, ...]
    estimated_tokens: int


class CodeBlockBatchPlanner:
    """按照估算 Token，而不是固定代码块数量分组。"""

    def __init__(
        self,
        *,
        max_input_tokens: int = 10000,
        max_blocks: int = 8,
    ) -> None:
        self._max_input_tokens = max_input_tokens
        self._max_blocks = max_blocks

    def build(
        self,
        blocks: list[ParsedCodeBlock],
        *,
        shared_context_tokens: int,
    ) -> list[CodeBlockBatch]:
        batches = []
        current = []
        current_tokens = shared_context_tokens

        for block in blocks:
            block_tokens = self._estimate_tokens(block.code)

            exceeds_budget = (
                current
                and current_tokens + block_tokens > self._max_input_tokens
            )
            exceeds_count = len(current) >= self._max_blocks

            if exceeds_budget or exceeds_count:
                batches.append(
                    CodeBlockBatch(
                        blocks=tuple(current),
                        estimated_tokens=current_tokens,
                    )
                )
                current = []
                current_tokens = shared_context_tokens

            current.append(block)
            current_tokens += block_tokens

        if current:
            batches.append(
                CodeBlockBatch(
                    blocks=tuple(current),
                    estimated_tokens=current_tokens,
                )
            )

        return batches

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 3)