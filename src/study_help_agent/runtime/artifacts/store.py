"""Loop Agent 的中间产物存储。

工具产生的大目录树、源码片段或分析报告不应永久进入 Prompt。本文件提供简单的
内存 Artifact Store，Prompt 中只暴露轻量引用，需要时再通过工具读取具体内容。
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol

from study_help_agent.runtime.state import ArtifactReference


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """保存一个产物的元数据及其真实内容。"""

    artifact_id: str
    artifact_type: str
    name: str
    summary: str
    content: Any

    def reference(self) -> ArtifactReference:
        """生成适合放进 LLM 上下文的轻量引用。"""

        return ArtifactReference(
            artifact_id=self.artifact_id,
            artifact_type=self.artifact_type,
            name=self.name,
            summary=self.summary,
        )


class ArtifactStore(Protocol):
    """定义 Loop Runtime 对产物存储所需的最小能力。"""

    def put(
        self,
        *,
        artifact_type: str,
        name: str,
        summary: str,
        content: Any,
    ) -> StoredArtifact:
        """保存产物并返回稳定引用。"""
        ...

    def get(self, artifact_id: str) -> StoredArtifact:
        """根据产物 ID 读取完整内容。"""
        ...

    def references(self, artifact_ids: tuple[str, ...]) -> tuple[ArtifactReference, ...]:
        """批量返回可放进上下文的轻量引用。"""
        ...


class InMemoryArtifactStore:
    """用于第一阶段和测试的进程内 Artifact Store 实现。"""

    def __init__(self) -> None:
        """初始化空的产物字典。"""

        self._artifacts: dict[str, StoredArtifact] = {}

    def put(
        self,
        *,
        artifact_type: str,
        name: str,
        summary: str,
        content: Any,
    ) -> StoredArtifact:
        """使用内容摘要生成稳定 ID，并保存完整产物。"""

        normalized_type = artifact_type.strip()
        normalized_name = name.strip()
        normalized_summary = summary.strip()
        if not normalized_type or not normalized_name or not normalized_summary:
            raise ValueError("Artifact type, name and summary cannot be empty")
        digest = sha256(
            f"{normalized_type}|{normalized_name}|{content!r}".encode("utf-8")
        ).hexdigest()[:24]
        artifact = StoredArtifact(
            artifact_id=f"artifact_{digest}",
            artifact_type=normalized_type,
            name=normalized_name,
            summary=normalized_summary,
            content=content,
        )
        self._artifacts[artifact.artifact_id] = artifact
        return artifact

    def get(self, artifact_id: str) -> StoredArtifact:
        """读取产物；未知 ID 直接抛出 KeyError，便于工具转换错误。"""

        return self._artifacts[artifact_id]

    def references(self, artifact_ids: tuple[str, ...]) -> tuple[ArtifactReference, ...]:
        """按传入顺序返回仍然存在的产物引用。"""

        return tuple(
            self._artifacts[artifact_id].reference()
            for artifact_id in artifact_ids
            if artifact_id in self._artifacts
        )
