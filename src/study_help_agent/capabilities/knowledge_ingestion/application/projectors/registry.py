"""Artifact 投影器协议和注册表。"""

from typing import Protocol

from study_help_agent.runtime.artifacts.store import StoredArtifact

from ...domain.models import KnowledgeAssetDraft


class ArtifactProjector(Protocol):
    """声明自己支持的 Artifact 类型并输出规范知识资产草稿。"""

    artifact_type: str

    def project(self, artifact: StoredArtifact) -> tuple[KnowledgeAssetDraft, ...]:
        """将业务产物投影为一个或多个知识资产。"""

        ...


class ArtifactProjectorRegistry:
    """按 Artifact 类型查找投影器，使入库主流程无需业务分支。"""

    def __init__(self, projectors: tuple[ArtifactProjector, ...] = ()) -> None:
        self._projectors: dict[str, ArtifactProjector] = {}
        for projector in projectors:
            self.register(projector)

    def register(self, projector: ArtifactProjector) -> None:
        """注册唯一投影器，防止同一种产物被重复解释。"""

        if projector.artifact_type in self._projectors:
            raise ValueError(f"Projector already registered: {projector.artifact_type}")
        self._projectors[projector.artifact_type] = projector

    def find(self, artifact_type: str) -> ArtifactProjector | None:
        """查找投影器；不支持的类型返回 None。"""

        return self._projectors.get(artifact_type)
