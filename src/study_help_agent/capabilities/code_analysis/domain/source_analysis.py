"""代码解释模块的确定性源码分析。

本模块只使用 Python AST，不调用 LLM、不连接数据库、
不读取 FastAPI Request。
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path

from study_help_agent.capabilities.code_analysis.domain.models import (
    CodeBlockType,
)


@dataclass(frozen=True, slots=True)
class ParsedCodeBlock:
    """等待 LLM 解释的一个代码块。"""

    name: str
    block_type: CodeBlockType

    line_start: int
    line_end: int

    code: str

    parent_class: str = ""
    docstring: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError(
                "代码块名称不能为空"
            )

        if self.line_start < 1:
            raise ValueError(
                "line_start 必须大于等于 1"
            )

        if self.line_end < self.line_start:
            raise ValueError(
                "line_end 不能小于 line_start"
            )


@dataclass(frozen=True, slots=True)
class ParsedSourceFile:
    """一个完成 AST 解析的 Python 文件。"""

    absolute_path: Path
    relative_path: str
    source_text: str

    blocks: list[ParsedCodeBlock] = field(
        default_factory=list
    )

    external_imports: list[str] = field(
        default_factory=list
    )

    internal_imports: list[str] = field(
        default_factory=list
    )


class PythonSourceAnalyzer:
    """将 Python 源码转换为可解释代码块。"""

    def parse(
        self,
        *,
        absolute_path: Path,
        relative_path: str,
        source_text: str,
    ) -> ParsedSourceFile:
        """解析源码。

        语法错误不会伪装成空文件，而是继续抛出 SyntaxError，
        由上层 Service/Runner 决定如何处理。
        """

        tree = ast.parse(
            source_text,
            filename=str(absolute_path),
        )

        blocks: list[ParsedCodeBlock] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            ):
                blocks.append(
                    self._function_block(
                        node=node,
                        source_text=source_text,
                        parent_class="",
                    )
                )

            elif isinstance(
                node,
                ast.ClassDef,
            ):
                blocks.append(
                    self._class_block(
                        node=node,
                        source_text=source_text,
                    )
                )

                for child in ast.iter_child_nodes(
                    node
                ):
                    if isinstance(
                        child,
                        (
                            ast.FunctionDef,
                            ast.AsyncFunctionDef,
                        ),
                    ):
                        blocks.append(
                            self._function_block(
                                node=child,
                                source_text=source_text,
                                parent_class=node.name,
                            )
                        )

        blocks.extend(
            self._top_level_blocks(
                tree=tree,
                source_text=source_text,
            )
        )

        blocks.sort(
            key=lambda item: (
                item.line_start,
                item.line_end,
                item.name,
            )
        )

        return ParsedSourceFile(
            absolute_path=(
                absolute_path.resolve()
            ),
            relative_path=relative_path,
            source_text=source_text,
            blocks=blocks,
        )


    def _function_block(
        self,
        *,
        node: (
            ast.FunctionDef
            | ast.AsyncFunctionDef
        ),
        source_text: str,
        parent_class: str,
    ) -> ParsedCodeBlock:
        block_type = (
            CodeBlockType.METHOD
            if parent_class
            else CodeBlockType.FUNCTION
        )

        return ParsedCodeBlock(
            name=node.name,
            block_type=block_type,
            parent_class=parent_class,
            line_start=node.lineno,
            line_end=(
                node.end_lineno
                or node.lineno
            ),
            docstring=(
                ast.get_docstring(node)
                or ""
            ),
            code=(
                ast.get_source_segment(
                    source_text,
                    node,
                )
                or ""
            ),
        )

    def _class_block(
        self,
        *,
        node: ast.ClassDef,
        source_text: str,
    ) -> ParsedCodeBlock:
        return ParsedCodeBlock(
            name=node.name,
            block_type=CodeBlockType.CLASS,
            parent_class="",
            line_start=node.lineno,
            line_end=(
                node.end_lineno
                or node.lineno
            ),
            docstring=(
                ast.get_docstring(node)
                or ""
            ),
            code=(
                ast.get_source_segment(
                    source_text,
                    node,
                )
                or ""
            ),
        )

    def _top_level_blocks(
        self,
        *,
        tree: ast.Module,
        source_text: str,
    ) -> list[ParsedCodeBlock]:
        lines = source_text.splitlines()

        candidate_nodes: list[ast.stmt] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.Import,
                    ast.ImportFrom,
                ),
            ):
                continue

            # 跳过模块 docstring。
            if (
                isinstance(node, ast.Expr)
                and isinstance(
                    node.value,
                    ast.Constant,
                )
                and isinstance(
                    node.value.value,
                    str,
                )
            ):
                continue

            if isinstance(node, ast.stmt):
                candidate_nodes.append(node)

        groups = self._group_by_affinity(
            candidate_nodes,
            lines,
        )

        result: list[ParsedCodeBlock] = []

        for group in groups:
            if not group:
                continue

            line_start = group[0].lineno

            last_node = group[-1]
            line_end = (
                last_node.end_lineno
                or last_node.lineno
            )

            code = "\n".join(
                lines[
                    line_start - 1
                    : line_end
                ]
            )

            meaningful_lines = [
                line
                for line in code.splitlines()
                if (
                    line.strip()
                    and not line
                    .strip()
                    .startswith("#")
                )
            ]

            if not meaningful_lines:
                continue

            result.append(
                ParsedCodeBlock(
                    name=self._block_label(
                        group
                    ),
                    block_type=(
                        CodeBlockType
                        .STATEMENT_GROUP
                    ),
                    line_start=line_start,
                    line_end=line_end,
                    code=code,
                )
            )

        return result

    def _group_by_affinity(
        self,
        nodes: list[ast.stmt],
        lines: list[str],
    ) -> list[list[ast.stmt]]:
        if not nodes:
            return []

        groups: list[list[ast.stmt]] = []
        current_group = [nodes[0]]

        for index in range(
            1,
            len(nodes),
        ):
            previous = nodes[index - 1]
            current = nodes[index]

            same_target = (
                self._extract_target(previous)
                ==
                self._extract_target(current)
            )

            adjacent = (
                self._are_adjacent(
                    previous,
                    current,
                    lines,
                )
            )

            if (
                same_target
                and self._extract_target(
                    current
                )
            ):
                current_group.append(current)
                continue

            if adjacent:
                current_group.append(current)
                continue

            groups.append(current_group)
            current_group = [current]

        groups.append(current_group)

        return groups

    @staticmethod
    def _are_adjacent(
        previous: ast.stmt,
        current: ast.stmt,
        lines: list[str],
    ) -> bool:
        previous_end = (
            previous.end_lineno
            or previous.lineno
        )

        current_start = current.lineno

        if current_start - previous_end > 2:
            return False

        for line_index in range(
            previous_end,
            current_start - 1,
        ):
            if not lines[line_index].strip():
                return False

        return True

    @staticmethod
    def _extract_target(
        node: ast.stmt,
    ) -> str | None:
        # workflow.add_node(...)
        if (
            isinstance(node, ast.Expr)
            and isinstance(
                node.value,
                ast.Call,
            )
            and isinstance(
                node.value.func,
                ast.Attribute,
            )
        ):
            owner = node.value.func.value

            if isinstance(owner, ast.Name):
                return owner.id

        # settings = ...
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    return target.id

        # value: str = ...
        if isinstance(
            node,
            ast.AnnAssign,
        ):
            if isinstance(
                node.target,
                ast.Name,
            ):
                return node.target.id

        if isinstance(node, ast.If):
            if (
                isinstance(
                    node.test,
                    ast.Compare,
                )
                and "__name__"
                in ast.unparse(node.test)
            ):
                return "__main_entry__"

            return "__condition__"

        if isinstance(node, ast.With):
            return "__with_block__"

        if isinstance(
            node,
            ast.AsyncWith,
        ):
            return "__async_with_block__"

        return None

    def _block_label(
        self,
        group: list[ast.stmt],
    ) -> str:
        first = group[0]

        if isinstance(first, ast.If):
            expression = ast.unparse(
                first.test
            )

            if "__name__" in expression:
                return "程序启动入口"

            return (
                "条件执行："
                f"{expression[:40]}"
            )

        target = self._extract_target(
            first
        )

        if target == "__with_block__":
            return "上下文管理代码块"

        if target == "__async_with_block__":
            return "异步上下文代码块"

        if (
            target
            and not target.startswith("__")
        ):
            return f"{target} 配置块"

        if isinstance(
            first,
            (
                ast.Assign,
                ast.AnnAssign,
            ),
        ):
            return "全局配置"

        if isinstance(first, ast.Expr):
            return "顶层执行"

        return "顶层代码块"


@dataclass(frozen=True, slots=True)
class FileImportContext:
    """一个文件的 import 关系。"""

    external_imports: list[str] = field(
        default_factory=list
    )

    internal_imports: list[str] = field(
        default_factory=list
    )

    imported_by: list[str] = field(
        default_factory=list
    )


@dataclass(frozen=True, slots=True)
class ProjectImportGraph:
    """整个项目的 import 关系。"""

    by_file: dict[
        str,
        FileImportContext,
    ] = field(default_factory=dict)


class ImportGraphBuilder:
    """根据已解析文件构建项目内部依赖关系。"""

    def build(
        self,
        parsed_files: list[ParsedSourceFile],
    ) -> ProjectImportGraph:
        module_to_file = {
            self._module_name(
                item.relative_path
            ): item.relative_path
            for item in parsed_files
        }

        external_by_file: dict[
            str,
            set[str],
        ] = {
            item.relative_path: set()
            for item in parsed_files
        }

        internal_by_file: dict[
            str,
            set[str],
        ] = {
            item.relative_path: set()
            for item in parsed_files
        }

        imported_by: dict[
            str,
            set[str],
        ] = {
            item.relative_path: set()
            for item in parsed_files
        }

        for parsed_file in parsed_files:
            tree = ast.parse(
                parsed_file.source_text,
                filename=str(
                    parsed_file.absolute_path
                ),
            )

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self._register_import(
                            imported_module=(
                                alias.name
                            ),
                            current_file=(
                                parsed_file
                                .relative_path
                            ),
                            module_to_file=(
                                module_to_file
                            ),
                            external=(
                                external_by_file
                            ),
                            internal=(
                                internal_by_file
                            ),
                            imported_by=imported_by,
                        )

                elif isinstance(
                    node,
                    ast.ImportFrom,
                ):
                    imported_module = (
                        node.module or ""
                    )

                    if node.level > 0:
                        imported_module = (
                            self._resolve_relative_import(
                                current_module=(
                                    self._module_name(
                                        parsed_file
                                        .relative_path
                                    )
                                ),
                                level=node.level,
                                imported_module=(
                                    imported_module
                                ),
                            )
                        )

                    self._register_import(
                        imported_module=(
                            imported_module
                        ),
                        current_file=(
                            parsed_file
                            .relative_path
                        ),
                        module_to_file=(
                            module_to_file
                        ),
                        external=(
                            external_by_file
                        ),
                        internal=(
                            internal_by_file
                        ),
                        imported_by=imported_by,
                    )

        result = {}

        for file_path in external_by_file:
            result[file_path] = (
                FileImportContext(
                    external_imports=sorted(
                        external_by_file[
                            file_path
                        ]
                    ),
                    internal_imports=sorted(
                        internal_by_file[
                            file_path
                        ]
                    ),
                    imported_by=sorted(
                        imported_by[file_path]
                    ),
                )
            )

        return ProjectImportGraph(
            by_file=result
        )

    @staticmethod
    def _module_name(
        relative_path: str,
    ) -> str:
        path = Path(relative_path)

        parts = list(path.with_suffix("").parts)

        if (
            parts
            and parts[-1] == "__init__"
        ):
            parts.pop()

        return ".".join(parts)

    def _register_import(
        self,
        *,
        imported_module: str,
        current_file: str,
        module_to_file: dict[str, str],
        external: dict[str, set[str]],
        internal: dict[str, set[str]],
        imported_by: dict[str, set[str]],
    ) -> None:
        if not imported_module:
            return

        matched_file = self._match_internal_file(
            imported_module,
            module_to_file,
        )

        if matched_file is None:
            root_package = (
                imported_module.split(".")[0]
            )

            if root_package:
                external[
                    current_file
                ].add(root_package)

            return

        internal[current_file].add(
            matched_file
        )

        imported_by[matched_file].add(
            current_file
        )

    @staticmethod
    def _match_internal_file(
        imported_module: str,
        module_to_file: dict[str, str],
    ) -> str | None:
        candidate = imported_module

        while candidate:
            if candidate in module_to_file:
                return module_to_file[
                    candidate
                ]

            if "." not in candidate:
                break

            candidate = candidate.rsplit(
                ".",
                1,
            )[0]

        return None

    @staticmethod
    def _resolve_relative_import(
        *,
        current_module: str,
        level: int,
        imported_module: str,
    ) -> str:
        parts = current_module.split(".")

        # 当前文件模块名最后一段是文件本身，
        # 相对导入从所在 package 开始。
        package_parts = parts[:-1]

        remove_count = max(
            level - 1,
            0,
        )

        if remove_count:
            package_parts = (
                package_parts[:-remove_count]
            )

        if imported_module:
            package_parts.extend(
                imported_module.split(".")
            )

        return ".".join(package_parts)

