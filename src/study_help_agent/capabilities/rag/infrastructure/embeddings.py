"""延迟加载 SentenceTransformer。"""

from threading import Lock
from pathlib import Path
from typing import Sequence


class SentenceTransformerEmbedder:
    """首次检索时才加载本地 Embedding 模型，避免应用启动被大模型阻塞。"""

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
                    from sentence_transformers import SentenceTransformer

                    device = "cuda" if torch.cuda.is_available() else "cpu"
                    self._model = SentenceTransformer(
                        self._model_name,
                        device=device,
                        local_files_only=self._local_files_only,
                        cache_folder=self._cache_folder,
                    )
        return self._model

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """批量编码并转换为与向量数据库无关的 Python 列表。"""

        if not texts:
            return []
        values = self._get_model().encode(list(texts))
        return [value.tolist() for value in values]
