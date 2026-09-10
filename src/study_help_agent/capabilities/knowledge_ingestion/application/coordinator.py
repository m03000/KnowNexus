"""协调 Artifact 投影与可靠入库，不执行切块和向量化。"""

from __future__ import annotations

from study_help_agent.runtime.artifacts.store import StoredArtifact

from ..domain.models import IngestionReceipt
from .ports import KnowledgeIngestionRepository
from .projectors.registry import ArtifactProjectorRegistry


class KnowledgeIngestionCoordinator:
    """把一个最终 Artifact 转换为一个或多个知识资产并写入 Outbox。"""

    def __init__(
        self,
        *,
        repository: KnowledgeIngestionRepository,
        projectors: ArtifactProjectorRegistry,
    ) -> None:
        self._repository = repository
        self._projectors = projectors

    def capture(self, artifact: StoredArtifact) -> tuple[IngestionReceipt, ...]:
        """投影并逐项持久化；没有注册投影器时明确返回空结果。"""

        projector = self._projectors.find(artifact.artifact_type)
        if projector is None:
            return ()
        return tuple(
            self._repository.upsert_and_enqueue(draft)
            for draft in projector.project(artifact)
        )
