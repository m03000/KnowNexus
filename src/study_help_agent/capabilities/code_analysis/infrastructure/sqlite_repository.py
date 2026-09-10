"""代码解释模块的 SQLite Repository。"""

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from study_help_agent.infrastructure.persistence.sqlite import (
    SqliteConnectionFactory,
)
from study_help_agent.capabilities.code_analysis.application.dto import (
    ExplainedFileContent,
    ProjectSummary,
    ProjectTreeFile,
    ProjectTreeFolder,
)
from study_help_agent.capabilities.code_analysis.domain.models import (
    CodeBlockExplanation,
    CodeBlockType,
    CodeSymbol,
    ExplainedProject,
    ExplainedSourceFile,
    ExplanationProjectStatus,
)
from study_help_agent.shared_kernel.source_code.paths import (
    normalize_project_path,
)


class SqliteCodeAnalysisRepository:
    """使用 SQLite 保存和查询代码解释结果。"""

    def __init__(
        self,
        connections: SqliteConnectionFactory,
    ) -> None:
        self._connections = connections

    def find_cached_project(
        self,
        project_path: str,
        fingerprint: str,
        analysis_fingerprint: str = "",
    ) -> ExplainedProject | None:
        """按源码与分析请求双指纹查询完整的已完成项目。"""

        normalized_path = normalize_project_path(project_path)

        with self._connections.connect() as connection:
            row = connection.execute(
                """
                SELECT id
                FROM code_explainer_projects
                WHERE project_path = ?
                  AND fingerprint = ?
                  AND analysis_fingerprint = ?
                  AND status = 'completed'
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    normalized_path,
                    fingerprint,
                    analysis_fingerprint,
                ),
            ).fetchone()

        if row is None:
            return None

        return self._load_explained_project(int(row["id"]))

    def save_project(
        self,
        project: ExplainedProject,
    ) -> int:
        """在一个事务中保存完整项目。"""

        normalized_path = normalize_project_path(project.project_path)

        scanned_at = (project.scanned_at or datetime.now(UTC)).isoformat()

        with self._connections.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO code_explainer_projects (
                    project_name,
                    project_path,
                    fingerprint,
                    analysis_fingerprint,
                    status,
                    project_summary,
                    total_files,
                    total_blocks,
                    scanned_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project.project_name,
                    normalized_path,
                    project.fingerprint,
                    project.analysis_fingerprint,
                    project.status.value,
                    project.project_summary,
                    project.total_files,
                    project.total_blocks,
                    scanned_at,
                ),
            )

            project_id = int(cursor.lastrowid)

            for source_file in project.files:
                connection.execute(
                    """
                    INSERT INTO
                        code_explainer_source_files (
                            project_id,
                            file_path,
                            relative_path,
                            source_text,
                            file_role
                        )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        source_file.file_path,
                        source_file.relative_path,
                        source_file.source_text,
                        source_file.file_role,
                    ),
                )

                for block in source_file.blocks:
                    connection.execute(
                        """
                        INSERT INTO
                            code_explainer_blocks (
                                project_id,
                                file_path,
                                code_name,
                                code_type,
                                parent_class,
                                line_start,
                                line_end,
                                explanation,
                                docstring,
                                full_code
                            )
                        VALUES (
                            ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?
                        )
                        """,
                        (
                            project_id,
                            source_file.file_path,
                            block.code_name,
                            block.code_type.value,
                            block.parent_class,
                            block.line_start,
                            block.line_end,
                            block.explanation,
                            block.docstring,
                            block.full_code,
                        ),
                    )

        return project_id

    def _load_explained_project(self, project_id: int) -> ExplainedProject | None:
        """恢复缓存所需的完整项目、文件与代码块领域对象。"""

        with self._connections.connect() as connection:
            project_row = connection.execute(
                """
                SELECT id, project_name, project_path, fingerprint,
                       analysis_fingerprint, status, project_summary, scanned_at
                FROM code_explainer_projects WHERE id = ?
                """,
                (project_id,),
            ).fetchone()
            if project_row is None:
                return None
            file_rows = connection.execute(
                """
                SELECT file_path, relative_path, source_text, file_role
                FROM code_explainer_source_files
                WHERE project_id = ? ORDER BY relative_path
                """,
                (project_id,),
            ).fetchall()
            block_rows = connection.execute(
                """
                SELECT file_path, code_name, code_type, parent_class,
                       line_start, line_end, explanation, docstring, full_code
                FROM code_explainer_blocks
                WHERE project_id = ? ORDER BY file_path, line_start
                """,
                (project_id,),
            ).fetchall()

        blocks_by_file: dict[str, list[CodeBlockExplanation]] = defaultdict(list)
        for row in block_rows:
            blocks_by_file[str(row["file_path"])].append(CodeBlockExplanation(
                code_name=str(row["code_name"]),
                code_type=CodeBlockType(row["code_type"]),
                parent_class=str(row["parent_class"] or ""),
                line_start=int(row["line_start"]),
                line_end=int(row["line_end"]),
                explanation=str(row["explanation"]),
                docstring=str(row["docstring"] or ""),
                full_code=str(row["full_code"] or ""),
            ))
        files = [ExplainedSourceFile(
            file_path=str(row["file_path"]),
            relative_path=str(row["relative_path"]),
            source_text=str(row["source_text"]),
            file_role=str(row["file_role"] or ""),
            blocks=blocks_by_file.get(str(row["file_path"]), []),
        ) for row in file_rows]
        return ExplainedProject(
            project_id=project_id,
            project_name=str(project_row["project_name"]),
            project_path=str(project_row["project_path"]),
            fingerprint=str(project_row["fingerprint"]),
            analysis_fingerprint=str(project_row["analysis_fingerprint"] or ""),
            status=ExplanationProjectStatus(project_row["status"]),
            project_summary=str(project_row["project_summary"] or ""),
            scanned_at=datetime.fromisoformat(str(project_row["scanned_at"])),
            files=files,
        )

    def get_project(
        self,
        project_id: int,
    ) -> ProjectSummary | None:
        """根据 ID 查询项目元数据。"""

        with self._connections.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    project_name,
                    project_path,
                    fingerprint,
                    status,
                    total_files,
                    total_blocks,
                    scanned_at,
                    project_summary
                FROM code_explainer_projects
                WHERE id = ?
                """,
                (project_id,),
            ).fetchone()

        if row is None:
            return None

        return self._row_to_summary(row)

    def list_projects(
        self,
    ) -> list[ProjectSummary]:
        """按最新版本列出已发布项目。"""

        with self._connections.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    project_name,
                    project_path,
                    fingerprint,
                    status,
                    total_files,
                    total_blocks,
                    scanned_at,
                    project_summary
                FROM code_explainer_projects
                WHERE status IN (
                    'completed',
                    'stale'
                )
                ORDER BY id DESC
                """
            ).fetchall()

        result: list[ProjectSummary] = []
        seen_paths: set[str] = set()

        for row in rows:
            normalized_path = normalize_project_path(
                row["project_path"]
            )

            if normalized_path in seen_paths:
                continue

            seen_paths.add(normalized_path)
            result.append(
                self._row_to_summary(row)
            )

        return result

    def delete_project(
        self,
        project_id: int,
    ) -> str | None:
        """删除项目；外键级联删除文件和代码块。"""

        with self._connections.connect() as connection:
            row = connection.execute(
                """
                SELECT project_path
                FROM code_explainer_projects
                WHERE id = ?
                """,
                (project_id,),
            ).fetchone()

            if row is None:
                return None

            connection.execute(
                """
                DELETE FROM code_explainer_projects
                WHERE id = ?
                """,
                (project_id,),
            )

        return str(row["project_path"])

    def get_project_tree(
        self,
        project_id: int,
    ) -> list[ProjectTreeFolder]:
        """构造目录、文件和符号树。"""

        with self._connections.connect() as connection:
            source_rows = connection.execute(
                """
                SELECT
                    file_path,
                    relative_path,
                    file_role
                FROM code_explainer_source_files
                WHERE project_id = ?
                ORDER BY relative_path
                """,
                (project_id,),
            ).fetchall()

            symbol_rows = connection.execute(
                """
                SELECT
                    file_path,
                    code_name,
                    code_type,
                    parent_class,
                    line_start,
                    line_end,
                    explanation
                FROM code_explainer_blocks
                WHERE project_id = ?
                  AND code_type IN (
                      'class',
                      'function',
                      'method'
                  )
                ORDER BY
                    file_path,
                    line_start
                """,
                (project_id,),
            ).fetchall()

        symbols_by_file: dict[
            str,
            list[CodeSymbol],
        ] = defaultdict(list)

        for row in symbol_rows:
            symbols_by_file[
                str(row["file_path"])
            ].append(
                CodeSymbol(
                    name=str(row["code_name"]),
                    symbol_type=CodeBlockType(
                        row["code_type"]
                    ),
                    start_line=int(
                        row["line_start"]
                    ),
                    end_line=int(
                        row["line_end"]
                    ),
                    parent_class=str(
                        row["parent_class"]
                        or ""
                    ),
                    summary=str(row["explanation"] or ""),
                )
            )

        files_by_folder: dict[
            str,
            list[ProjectTreeFile],
        ] = defaultdict(list)

        for row in source_rows:
            relative_path = str(
                row["relative_path"]
            )

            relative = Path(relative_path)
            parent = relative.parent.as_posix()

            if parent == ".":
                parent = ""

            file_path = str(row["file_path"])

            files_by_folder[parent].append(
                ProjectTreeFile(
                    file_name=relative.name,
                    file_path=file_path,
                    file_role=str(
                        row["file_role"]
                        or ""
                    ),
                    relative_path=relative_path,
                    symbols=symbols_by_file.get(
                        file_path,
                        [],
                    ),
                )
            )

        return [
            ProjectTreeFolder(
                folder=folder,
                files=sorted(
                    files,
                    key=lambda item: (
                        item.file_name.lower()
                    ),
                ),
            )
            for folder, files
            in sorted(files_by_folder.items())
        ]

    def get_file_content(
        self,
        project_id: int,
        file_path: str,
    ) -> ExplainedFileContent | None:
        """读取源码快照和代码块解释。"""

        with self._connections.connect() as connection:
            source_row = connection.execute(
                """
                SELECT
                    file_path,
                    relative_path,
                    source_text,
                    file_role
                FROM code_explainer_source_files
                WHERE project_id = ?
                  AND file_path = ?
                """,
                (
                    project_id,
                    file_path,
                ),
            ).fetchone()

            if source_row is None:
                return None

            block_rows = connection.execute(
                """
                SELECT
                    code_name,
                    code_type,
                    parent_class,
                    line_start,
                    line_end,
                    explanation,
                    docstring,
                    full_code
                FROM code_explainer_blocks
                WHERE project_id = ?
                  AND file_path = ?
                ORDER BY line_start
                """,
                (
                    project_id,
                    file_path,
                ),
            ).fetchall()

        blocks = [
            CodeBlockExplanation(
                code_name=str(row["code_name"]),
                code_type=CodeBlockType(
                    row["code_type"]
                ),
                parent_class=str(
                    row["parent_class"]
                    or ""
                ),
                line_start=int(
                    row["line_start"]
                ),
                line_end=int(
                    row["line_end"]
                ),
                explanation=str(
                    row["explanation"]
                ),
                docstring=str(
                    row["docstring"]
                    or ""
                ),
                full_code=str(
                    row["full_code"]
                    or ""
                ),
            )
            for row in block_rows
        ]

        source_text = str(
            source_row["source_text"]
        )

        return ExplainedFileContent(
            file_name=Path(
                str(source_row["relative_path"])
            ).name,
            file_path=str(
                source_row["file_path"]
            ),
            file_role=str(
                source_row["file_role"]
                or ""
            ),
            source_lines=source_text.splitlines(),
            blocks=blocks,
        )

    @staticmethod
    def _row_to_summary(
        row,
    ) -> ProjectSummary:
        """把 SQLite Row 转换为应用 DTO。"""

        return ProjectSummary(
            project_id=int(row["id"]),
            project_name=str(
                row["project_name"]
            ),
            project_path=str(
                row["project_path"]
            ),
            fingerprint=str(
                row["fingerprint"]
            ),
            status=ExplanationProjectStatus(
                row["status"]
            ),
            total_files=int(
                row["total_files"]
            ),
            total_blocks=int(
                row["total_blocks"]
            ),
            scanned_at=str(
                row["scanned_at"]
            ),
            project_summary=str(row["project_summary"] or ""),
        )
