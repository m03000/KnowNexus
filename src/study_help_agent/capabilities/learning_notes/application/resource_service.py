"""学习资源前置处理的薄应用服务。

服务只协调端口并校验边界，不包含平台下载、格式解析或模型细节。
"""

from collections.abc import Callable

from study_help_agent.capabilities.learning_notes.domain import (
    AcquiredResource,
    ExtractedContent,
)

from .resource_ports import LearningContentExtractor, LearningResourceAcquirer


class LearningResourceService:
    """向工具层提供资源获取和内容提取两个独立用例。"""

    def __init__(
        self,
        *,
        acquirer: LearningResourceAcquirer,
        extractor: LearningContentExtractor,
    ) -> None:
        self._acquirer = acquirer
        self._extractor = extractor

    def acquire(self, source: str) -> AcquiredResource:
        """获取非空来源，实际下载或复制由基础设施实现。"""

        normalized = source.strip()
        if not normalized:
            raise ValueError("资源链接或本地路径不能为空")
        return self._acquirer.acquire(normalized)

    def extract(
        self,
        resource: AcquiredResource,
        *,
        progress: Callable[[str, str], None] | None = None,
    ) -> ExtractedContent:
        """从已经受控保存的资源中提取内容。"""

        return self._extractor.extract(resource, progress=progress)

    def release(self, resource: AcquiredResource) -> bool:
        """释放完成提取后不再需要的受控资源副本。"""

        return self._acquirer.release(resource)
