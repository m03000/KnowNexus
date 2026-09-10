"""SQLite 知识点仓储实现。"""
from study_help_agent.infrastructure.persistence.sqlite import SqliteConnectionFactory


class SqliteKnowledgePointRepository:
    def __init__(self, connections: SqliteConnectionFactory) -> None:
        self._connections = connections

    def find_by_name(self, name: str) -> dict | None:
        with self._connections.connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_points WHERE name = ?", (name,)
            ).fetchone()
            return dict(row) if row else None

    def link_point_to_note(self, point_id: str, note_filename: str,
                           segment_index: int, relevance: str) -> None:
        with self._connections.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO note_point_links
                   (point_id, note_filename, segment_index, relevance)
                   VALUES (?, ?, ?, ?)""",
                (point_id, note_filename, segment_index, relevance),
            )

    def save_point(self, point_id: str, name: str, description: str,
                   domain: str, entity_type: str) -> None:
        with self._connections.connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_points
                   (point_id, name, description, domain, entity_type)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description = excluded.description,
                    domain = excluded.domain,
                    entity_type = excluded.entity_type,
                    updated_at = datetime('now')
                """,
                (point_id, name, description, domain, entity_type),
            )

    def get_points_by_note(self, note_filename: str) -> list[dict]:
        """查询某篇笔记关联的所有知识点（含段内位置）。"""
        with self._connections.connect() as conn:
            rows = conn.execute(
                """
                SELECT kp.*, npl.segment_index, npl.relevance
                FROM note_point_links npl
                JOIN knowledge_points kp ON kp.point_id = npl.point_id
                WHERE npl.note_filename = ?
                ORDER BY npl.segment_index
                """,
                (note_filename,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_notes_by_point(self, point_id: str) -> list[dict]:
        """查询某个知识点涉及的所有笔记段落。"""
        with self._connections.connect() as conn:
            rows = conn.execute(
                """
                SELECT npl.*, kp.name
                FROM note_point_links npl
                JOIN knowledge_points kp ON kp.point_id = npl.point_id
                WHERE npl.point_id = ?
                ORDER BY npl.segment_index
                """,
                (point_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_all_points(self) -> list[dict]:
        """列出所有知识点（供提取去重与前端图谱使用）。"""
        with self._connections.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_points ORDER BY name"
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_links_for_note(self, note_filename: str) -> None:
        """删除笔记时级联清理关联。"""
        with self._connections.connect() as conn:
            conn.execute(
                "DELETE FROM note_point_links WHERE note_filename = ?",
                (note_filename,),
            )

    def retain_links_for_note(
        self, note_filename: str, links: list[tuple[str, int]]
    ) -> None:
        """原子修剪旧关联，避免文档局部修改后残留过期段落定位。"""

        with self._connections.connect() as conn:
            if not links:
                conn.execute(
                    "DELETE FROM note_point_links WHERE note_filename = ?",
                    (note_filename,),
                )
                return
            predicates = " OR ".join(
                "(point_id = ? AND segment_index = ?)" for _ in links
            )
            parameters: list[object] = [note_filename]
            for point_id, segment_index in links:
                parameters.extend((point_id, segment_index))
            conn.execute(
                f"""
                DELETE FROM note_point_links
                WHERE note_filename = ? AND NOT ({predicates})
                """,
                parameters,
            )

