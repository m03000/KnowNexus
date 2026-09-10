"""知识点仓储端口协议。"""
from typing import Protocol


class KnowledgePointRepository(Protocol):
    def find_by_name(self, name: str) -> dict | None: ...
    """按名称查找已有知识点，用于去重。返回 None 表示不存在。"""

    def save_point(self, point_id: str, name: str, description: str,
                   domain: str, entity_type: str) -> None: ...
    """插入新知识点。"""

    def link_point_to_note(self, point_id: str, note_filename: str,
                           segment_index: int, relevance: str) -> None: ...
    """建立知识点与笔记段落关联。"""

    def get_points_by_note(self, note_filename: str) -> list[dict]: ...
    """查询某篇笔记关联的所有知识点。"""

    def get_notes_by_point(self, point_id: str) -> list[dict]: ...
    """查询某个知识点涉及的所有笔记段落。"""

    def list_all_points(self) -> list[dict]: ...
    """列出所有知识点（供前端图谱使用）。"""

    def delete_links_for_note(self, note_filename: str) -> None: ...
    """删除笔记时级联清理关联。"""

    def retain_links_for_note(
        self, note_filename: str, links: list[tuple[str, int]]
    ) -> None: ...
    """成功重提取后只保留本次确认的知识点—段落关联。"""
