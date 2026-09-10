"""无外部依赖排名融合算法。"""

from collections import defaultdict

from .models import RetrievedChunk


class ReciprocalRankFusion:
    """按文档 ID 融合多路排名，并保留所有命中通道。"""

    def __init__(self, rank_constant: int = 60) -> None:
        if rank_constant <= 0:
            raise ValueError("rank_constant 必须大于 0")
        self._rank_constant = rank_constant

    def fuse(
        self, rankings: list[list[RetrievedChunk]], limit: int
    ) -> list[RetrievedChunk]:
        """计算 RRF 分数、合并通道并返回前 limit 个文档块。"""

        scores: dict[str, float] = defaultdict(float)
        chunks: dict[str, RetrievedChunk] = {}
        channels: dict[str, set[str]] = defaultdict(set)
        for ranking in rankings:
            for rank, chunk in enumerate(ranking, 1):
                scores[chunk.chunk_id] += 1.0 / (self._rank_constant + rank)
                chunks.setdefault(chunk.chunk_id, chunk)
                channels[chunk.chunk_id].update(chunk.retrieval_channels)
        ordered = sorted(scores, key=scores.get, reverse=True)[:limit]
        return [
            chunks[chunk_id].with_updates(
                fusion_score=scores[chunk_id],
                retrieval_channels=tuple(sorted(channels[chunk_id])),
            )
            for chunk_id in ordered
        ]
