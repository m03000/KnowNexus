"""学习资源获取与内容提取的应用层端口。"""

from collections.abc import Callable
from typing import Protocol

from study_help_agent.capabilities.learning_notes.domain import (
    AcquiredResource,
    ExtractedContent,
)


class LearningResourceAcquirer(Protocol):
    """把本地路径或外部链接转换成受控本地资源。"""

    def acquire(self, source: str) -> AcquiredResource:
        """获取一个资源并返回可审计元数据。"""
        ...

    def release(self, resource: AcquiredResource) -> bool:
        """删除受控目录中的临时副本，不得删除用户原始文件。"""
        ...


class LearningContentExtractor(Protocol):
    """根据文件类型提取普通文本、音频文本和画面文本。"""

    def extract(
        self,
        resource: AcquiredResource,
        *,
        progress: Callable[[str, str], None] | None = None,
    ) -> ExtractedContent:
        """提取资源内容，不负责语义改写。"""
        ...
