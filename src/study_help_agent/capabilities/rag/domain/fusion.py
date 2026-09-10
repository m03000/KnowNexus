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
        self, rankings: list[list[RetrievedChunk]], limit: int,
        weights: list[float] | None = None,
    ) -> list[RetrievedChunk]:
        """计算 RRF 分数、合并通道并返回前 limit 个文档块。"""

        scores: dict[str, float] = defaultdict(float)
        chunks: dict[str, RetrievedChunk] = {}
        channels: dict[str, set[str]] = defaultdict(set)
        channel_weights = weights or [1.0] * len(rankings)
        if len(channel_weights) != len(rankings):
            raise ValueError("weights 数量必须与 rankings 一致")
        for ranking, weight in zip(rankings, channel_weights, strict=True):
            for rank, chunk in enumerate(ranking, 1):
                key = self._evidence_key(chunk)
                scores[key] += float(weight) / (self._rank_constant + rank)
                chunks.setdefault(key, chunk)
                channels[key].update(chunk.retrieval_channels)
        ordered = sorted(scores, key=scores.get, reverse=True)[:limit]
        return [
            chunks[chunk_id].with_updates(
                fusion_score=scores[chunk_id],
                retrieval_channels=tuple(sorted(channels[chunk_id])),
            )
            for chunk_id in ordered
        ]

    @staticmethod
    def _evidence_key(chunk: RetrievedChunk) -> str:
        source_id = str(chunk.metadata.get("source_id") or "")
        segment_key = str(chunk.metadata.get("segment_key") or "")
        if source_id and segment_key:
            return f"evidence:{source_id}:{segment_key}"
        logical_key = str(chunk.metadata.get("logical_key") or "")
        if chunk.asset_id and logical_key:
            return f"asset:{chunk.asset_id}:{logical_key}"
        return chunk.chunk_id
