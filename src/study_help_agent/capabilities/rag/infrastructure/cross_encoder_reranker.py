"""延迟加载 CrossEncoder，对混合召回候选进行第二阶段精排。"""

from threading import Lock
from pathlib import Path

from study_help_agent.capabilities.rag.domain.models import RetrievedChunk


class CrossEncoderReranker:
    """保留原版问题-文档对打分、降序排列和 Top-K 截断逻辑。"""

    def __init__(
        self,
        model_name: str,
        *,
        local_files_only: bool = True,
        cache_folder: Path | str | None = None,
    ) -> None:
        self._model_name = model_name
        self._local_files_only = local_files_only
        self._cache_folder = str(cache_folder) if cache_folder is not None else None
        self._model = None
        self._lock = Lock()

    def _get_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    import torch
                    from sentence_transformers import CrossEncoder

                    from study_help_agent.infrastructure.models.local_files import resolve_local_model
                    model_path = str(resolve_local_model(self._model_name, self._cache_folder)) if self._local_files_only and self._cache_folder else self._model_name
                    self._model = CrossEncoder(
                        model_path,
                        max_length=512,
                        device="cuda" if torch.cuda.is_available() else "cpu",
                        local_files_only=self._local_files_only,
                        cache_folder=self._cache_folder,
                    )
        return self._model

    def rerank(
        self, query: str, candidates: list[RetrievedChunk], limit: int
    ) -> list[RetrievedChunk]:
        """内容去重后计算 CrossEncoder 分数并返回前 limit 项。"""

        unique = list({chunk.chunk_id: chunk for chunk in candidates}.values())
        if not unique:
            return []
        scores = self._get_model().predict([(query, chunk.text) for chunk in unique])
        ranked = sorted(
            zip(unique, scores), key=lambda item: float(item[1]), reverse=True
        )[:limit]
        return [
            chunk.with_updates(rerank_score=float(score)) for chunk, score in ranked
        ]
