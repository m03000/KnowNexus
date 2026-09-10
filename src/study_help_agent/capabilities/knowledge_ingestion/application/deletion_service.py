"""将前端业务删除转换成可靠的知识索引删除任务。"""

from typing import Protocol


class KnowledgeDeletionRepository(Protocol):
    """删除协调器需要的最小仓储端口。"""

    def request_delete_by_source_key(self, stable_source_key: str) -> int: ...

    def request_delete_by_source_prefix(self, source_prefix: str) -> int: ...


class KnowledgeDeletionService:
    """立即移除关键词可见性，并由 Outbox 异步清理向量和规范资产。"""

    def __init__(self, repository: KnowledgeDeletionRepository) -> None:
        self._repository = repository

    def delete_note(self, filename: str) -> int:
        """删除与前端笔记文件对应的个人知识资产。"""

        return self._repository.request_delete_by_source_key(f"note-file:{filename}")

    def delete_code_project(self, fingerprint: str) -> int:
        """删除一个项目指纹下的报告和全部代码块资产。"""

        return self._repository.request_delete_by_source_prefix(
            f"project:{fingerprint}:"
        )

    def delete_document(self, document_id: str) -> int:
        """删除个人文档对应的规范资产、关键词切块并排队清理向量。"""
        return self._repository.request_delete_by_source_key(
            f"document:{document_id}"
        )
