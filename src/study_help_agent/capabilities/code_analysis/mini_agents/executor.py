"""本地代码分析条件图的节点实现和同步执行入口。

确定性节点负责安全扫描、源码读取、AST 与导入图；LLM 节点只负责项目范围选择、
文件职责、项目摘要和代码块解释。单个文件失败会被记录并有界重试，不会使整个项目
直接失败。最终执行器把图状态恢复为既有 ``ExplainedProject`` 领域模型。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from hashlib import sha256
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from study_help_agent.observability.context import submit_with_trace

from study_help_agent.capabilities.code_analysis.application.ports import (
    SourceProjectInspector,
)
from study_help_agent.capabilities.code_analysis.domain.models import (
    CodeBlockExplanation,
    CodeBlockType,
    ExplainedProject,
    ExplainedSourceFile,
    ExplanationProjectStatus,
)
from study_help_agent.capabilities.code_analysis.domain.source_analysis import (
    ImportGraphBuilder,
    PythonSourceAnalyzer,
)
from study_help_agent.capabilities.code_analysis.llm.operations import (
    CodeAnalysisOperations,
)
from study_help_agent.shared_kernel.source_code.reader import read_python_source

from .graph import build_code_analysis_graph
from .state import CodeAnalysisState
from study_help_agent.capabilities.code_analysis.llm.cost_logging import (
    invoke_with_cost_log,
)
from study_help_agent.runtime.cancellation import AgentCancelledError, CancellationToken


class ScopePlanOutput(BaseModel):
    """限制 LLM 只能返回候选文件路径和简短选择理由。"""

    selected_paths: list[str] = Field(default_factory=list)
    reason: str = ""


class CodeAnalysisGraphNodes:
    """实现代码分析图节点，每个方法只产生可合并的状态增量。"""

    def __init__(
        self,
        *,
        llm: BaseChatModel,
        inspector: SourceProjectInspector,
        operations: CodeAnalysisOperations,
        scan_max_files: int,
        source_max_bytes: int,
        max_parallelism: int = 4,
    ) -> None:
        """注入文件系统端口、原子 LLM 操作和两级安全预算。"""

        self._inspector = inspector
        self._operations = operations
        self._scan_max_files = scan_max_files
        self._source_max_bytes = source_max_bytes
        self._max_parallelism = max(1, max_parallelism)
        self._analyzer = PythonSourceAnalyzer()
        self._imports = ImportGraphBuilder()
        self._scope_llm = llm.with_structured_output(
            ScopePlanOutput,
            method="function_calling",
        )

    def inspect_and_prepare(self, state: CodeAnalysisState) -> dict[str, Any]:
        """校验本地目录，读取 Python 文件并建立 AST 与导入关系。"""

        self._check_cancelled(state)
        snapshot = self._inspector.inspect(
            project_path=Path(state["project_path"]),
            max_files=self._scan_max_files,
        )
        if not snapshot.source_files:
            raise ValueError("本地项目中没有可分析的 Python 文件")

        parsed_files = []
        errors: list[str] = []
        for source_file in snapshot.source_files:
            self._check_cancelled(state)
            try:
                source = read_python_source(
                    source_file.absolute_path,
                    max_bytes=self._source_max_bytes,
                )
                parsed_files.append(
                    self._analyzer.parse(
                        absolute_path=source_file.absolute_path,
                        relative_path=source_file.relative_path,
                        source_text=source,
                    )
                )
            except Exception as error:
                errors.append(f"{source_file.relative_path}: {error}")

        if not parsed_files:
            raise ValueError("所有 Python 文件都无法读取或解析")
        import_graph = self._imports.build(parsed_files)
        prepared = {
            str(item.absolute_path): self._serialize_file(item)
            for item in parsed_files
        }
        contexts = {
            path: {
                "external_imports": list(value.external_imports),
                "internal_imports": list(value.internal_imports),
                "imported_by": list(value.imported_by),
            }
            for path, value in import_graph.by_file.items()
        }
        return {
            "snapshot": snapshot,
            "project_name": snapshot.project_root.name,
            "fingerprint": snapshot.fingerprint,
            "prepared_files": prepared,
            "import_contexts": contexts,
            "errors": errors,
            "retry_count": 0,
            "file_contexts": {},
            "explained_files": [],
            "failed_paths": [],
        }

    def plan_scope(self, state: CodeAnalysisState) -> dict[str, Any]:
        """单文件模式精确定位，项目模式让 LLM 从受控清单选择关键文件。"""

        self._check_cancelled(state)
        by_relative = {
            data["relative_path"]: absolute
            for absolute, data in state["prepared_files"].items()
        }
        if state["mode"] in {"file", "files"}:
            targets = (
                [state["target_file"]]
                if state["mode"] == "file"
                else state.get("target_files", [])
            )
            matches: list[str] = []
            for raw_target in targets:
                target = raw_target.replace("\\", "/").strip()
                current = [
                    path for path in by_relative
                    if path == target or path.endswith("/" + target)
                ]
                if len(current) != 1:
                    raise ValueError(f"目标文件必须唯一存在于项目中：{raw_target}")
                if current[0] not in matches:
                    matches.append(current[0])
            if not matches:
                raise ValueError("至少需要指定一个目标文件")
            return {"selected_paths": matches, "requested_paths": matches}

        limit = min(max(int(state.get("max_files", 8)), 1), 20)
        inventory = self._inventory(state)
        prompt = (
            "你是代码分析范围规划器。只能从候选 path 中选择文件；"
            "优先入口、核心业务、领域模型、基础设施边界和高连接度文件。"
            "排除测试、迁移、缓存和生成代码，除非用户目标明确要求。最多选择 "
            f"{limit} 个。用户目标：{state.get('analysis_goal', '')}\n"
            f"候选文件：{inventory}"
        )
        try:
            raw = invoke_with_cost_log(
                self._scope_llm,
                prompt,
                stage="scope_planning",
            )
            self._check_cancelled(state)
            plan = (
                raw
                if isinstance(raw, ScopePlanOutput)
                else ScopePlanOutput.model_validate(raw)
            )
            selected = list(
                dict.fromkeys(path for path in plan.selected_paths if path in by_relative)
            )[:limit]
        except Exception:
            selected = []
        if not selected:
            selected = self._fallback_scope(inventory, limit)
        return {"selected_paths": selected, "requested_paths": selected}

    def analyze_file_roles(self, state: CodeAnalysisState) -> dict[str, Any]:
        """为选中且尚未成功的文件生成职责和符号角色。"""

        self._check_cancelled(state)
        token = state.get("cancellation_token")
        file_contexts = dict(state.get("file_contexts", {}))
        failed: list[str] = []
        errors = list(state.get("errors", []))
        relative_to_pair = {
            data["relative_path"]: (absolute, data)
            for absolute, data in state["prepared_files"].items()
        }
        def analyze_one(path: str):
            self._check_cancelled(state)
            absolute, data = relative_to_pair[path]
            if absolute in file_contexts:
                return path, None
            result = self._operations.analyze_file_context(
                {
                    "current_file_path": absolute,
                    "current_file_data": data,
                    "import_contexts": state["import_contexts"],
                    "cancellation_token": token,
                }
            )
            return path, result

        pending = [
            path for path in state["selected_paths"]
            if relative_to_pair[path][0] not in file_contexts
        ]
        results: dict[str, dict[str, Any]] = {}
        if pending:
            executor = ThreadPoolExecutor(
                max_workers=min(self._max_parallelism, len(pending)),
                thread_name_prefix="code-role-llm",
            )
            futures = {}
            try:
                futures = {submit_with_trace(executor, analyze_one, path): path for path in pending}
                for future in as_completed(futures):
                    self._check_cancelled(state)
                    path = futures[future]
                    try:
                        _, result = future.result()
                        if result is not None:
                            results[path] = result
                    except AgentCancelledError:
                        raise
                    except Exception as error:
                        if state.get("retry_count", 0) >= 1:
                            absolute, data = relative_to_pair[path]
                            imports = state.get("import_contexts", {}).get(path, {})
                            symbols = [block["name"] for block in data.get("blocks", [])]
                            results[path] = {
                                "file_contexts": {
                                    absolute: {
                                        **data,
                                        "file_role": self._fallback_file_role(
                                            path=path,
                                            symbols=symbols,
                                            internal_imports=imports.get("internal_imports", []),
                                            imported_by=imports.get("imported_by", []),
                                        ),
                                        "function_roles": {},
                                    }
                                }
                            }
                            errors.append(
                                f"文件职责模型连续失败，已使用确定性职责继续分析 {path}: {error}"
                            )
                        else:
                            failed.append(path)
                            errors.append(f"文件职责分析失败 {path}: {error}")
            finally:
                cancelled = bool(token and token.cancelled)
                if cancelled:
                    for future in futures:
                        future.cancel()
                executor.shutdown(wait=not cancelled, cancel_futures=cancelled)

        for path in state["selected_paths"]:
            result = results.get(path)
            if result is not None:
                file_contexts.update(result["file_contexts"])
        return {
            "file_contexts": file_contexts,
            "failed_paths": failed,
            "errors": errors,
        }

    def summarize_project(self, state: CodeAnalysisState) -> dict[str, Any]:
        """根据成功的文件职责生成带明确覆盖边界的项目摘要。"""

        self._check_cancelled(state)
        if not state.get("file_contexts"):
            return {"project_summary": "没有文件完成职责分析，无法生成项目摘要。"}
        result = self._operations.summarize_project(
            {
                "file_contexts": state["file_contexts"],
                "cancellation_token": state.get("cancellation_token"),
            }
        )
        coverage_note = (
            f"\n\n分析范围：选择 {len(state['requested_paths'])} 个文件，"
            f"完成职责分析 {len(state['file_contexts'])} 个。"
        )
        return {"project_summary": result["project_summary"] + coverage_note}

    def explain_files(self, state: CodeAnalysisState) -> dict[str, Any]:
        """并行解释待处理文件；增量轮次只提交尚未完成的文件。"""

        self._check_cancelled(state)
        explained_by_path = {
            item["relative_path"]: {
                **item,
                "blocks": list(item.get("blocks", [])),
            }
            for item in state.get("explained_files", [])
        }
        missing_by_file = state.get("missing_block_ids_by_file", {})
        failed = list(state.get("failed_paths", []))
        errors = list(state.get("errors", []))
        pending = [
            (absolute, data)
            for absolute, data in state.get("file_contexts", {}).items()
            if data["relative_path"] in state["selected_paths"]
            and (
                data["relative_path"] not in explained_by_path
                or bool(missing_by_file.get(data["relative_path"]))
            )
        ]

        def explain_one(absolute: str, data: dict[str, Any]):
            self._check_cancelled(state)
            return self._operations.explain_file({
                "current_file_path": absolute,
                "current_file_data": data,
                "project_summary": state["project_summary"],
                "target_block_ids": missing_by_file.get(data["relative_path"], []),
                "cancellation_token": state.get("cancellation_token"),
            })

        results: dict[str, dict[str, Any]] = {}
        if pending:
            executor = ThreadPoolExecutor(
                max_workers=min(self._max_parallelism, len(pending)),
                thread_name_prefix="code-file-explain-llm",
            )
            futures = {}
            try:
                futures = {
                    submit_with_trace(executor, explain_one, absolute, data): data["relative_path"]
                    for absolute, data in pending
                }
                for future in as_completed(futures):
                    self._check_cancelled(state)
                    path = futures[future]
                    try:
                        results[path] = future.result()
                    except AgentCancelledError:
                        raise
                    except Exception as error:
                        if path not in failed:
                            failed.append(path)
                        errors.append(f"代码块解释失败 {path}: {error}")
            finally:
                cancelled = bool(state.get("cancellation_token") and state["cancellation_token"].cancelled)
                if cancelled:
                    for future in futures:
                        future.cancel()
                executor.shutdown(wait=not cancelled, cancel_futures=cancelled)

        for path in state["selected_paths"]:
            if path not in results:
                continue
            result = results[path]
            errors.extend(
                f"代码块批次失败 {path}: {message}"
                for message in result.get("errors", [])
            )
            incoming = result["explained_files"][0]
            current = explained_by_path.get(path, {**incoming, "blocks": []})
            block_map = {
                self._serialized_block_id(block): block
                for block in current.get("blocks", [])
            }
            block_map.update({
                self._serialized_block_id(block): block
                for block in incoming.get("blocks", [])
            })
            explained_by_path[path] = {**current, **incoming, "blocks": list(block_map.values())}
        return {
            "explained_files": list(explained_by_path.values()),
            "failed_paths": failed,
            "errors": errors,
        }

    def validate_result(self, state: CodeAnalysisState) -> dict[str, Any]:
        """用确定性集合计算文件覆盖率和代码块覆盖率。"""

        self._check_cancelled(state)
        requested = set(state["requested_paths"])
        completed_files = {
            item["relative_path"] for item in state.get("explained_files", [])
        } & requested
        prepared_by_path = {
            item["relative_path"]: item
            for item in state.get("prepared_files", {}).values()
        }
        expected_blocks = sum(
            len(prepared_by_path.get(path, {}).get("blocks", []))
            for path in requested
        )
        completed_ids_by_file = {
            item["relative_path"]: {
                self._serialized_block_id(block) for block in item.get("blocks", [])
            }
            for item in state.get("explained_files", [])
            if item["relative_path"] in requested
        }
        expected_ids_by_file = {
            path: {
                self._serialized_block_id(block)
                for block in prepared_by_path.get(path, {}).get("blocks", [])
            }
            for path in requested
        }
        missing_by_file = {
            path: sorted(expected_ids - completed_ids_by_file.get(path, set()))
            for path, expected_ids in expected_ids_by_file.items()
            if expected_ids - completed_ids_by_file.get(path, set())
        }
        completed_blocks = sum(len(ids) for ids in completed_ids_by_file.values())
        structure_coverage = len(completed_files) / len(requested) if requested else 0.0
        block_coverage = (
            min(completed_blocks / expected_blocks, 1.0)
            if expected_blocks else structure_coverage
        )
        coverage = min(structure_coverage, block_coverage)
        missing = sorted(set(missing_by_file) | (requested - completed_files))
        status = "completed" if coverage == 1 else "partial" if completed_files else "failed"
        return {
            "expected_file_count": len(requested),
            "expected_block_count": expected_blocks,
            "completed_block_count": completed_blocks,
            "structure_coverage": structure_coverage,
            "block_coverage": block_coverage,
            "coverage": coverage,
            "completion_status": status,
            "failed_paths": missing,
            "missing_block_ids_by_file": missing_by_file,
        }

    def route_after_validation(self, state: CodeAnalysisState) -> str:
        """失败文件最多重试一次，防止局部推理变成无界 Loop。"""

        if (
            state["completion_status"] != "completed"
            and state.get("failed_paths")
            and state.get("retry_count", 0) < 2
        ):
            return "retry"
        return "finish"

    def prepare_retry(self, state: CodeAnalysisState) -> dict[str, Any]:
        """下一轮只处理失败文件，保留已经完成的解释结果。"""

        return {
            "selected_paths": list(state["failed_paths"]),
            "failed_paths": [],
            "retry_count": state.get("retry_count", 0) + 1,
        }

    @staticmethod
    def _serialized_block_id(block: dict[str, Any]) -> str:
        """为 AST 块和解释块生成相同的稳定标识。"""

        existing = str(block.get("block_id") or "").strip()
        if existing:
            return existing
        return ":".join((
            str(block.get("block_type") or "block"),
            str(block.get("parent_class") or ""),
            str(block.get("name") or block.get("code_name") or "anonymous"),
            str(block.get("line_start") or 1),
            str(block.get("line_end") or block.get("line_start") or 1),
        ))

    @staticmethod
    def _fallback_file_role(
        *, path: str, symbols: list[str],
        internal_imports: list[str], imported_by: list[str],
    ) -> str:
        """在职责模型连续失败时根据 AST 与导入事实生成无幻觉兜底描述。"""

        symbol_text = "、".join(symbols[:12]) or "无显式类或函数"
        dependency_text = "、".join(internal_imports[:8]) or "无项目内导入"
        caller_text = "、".join(imported_by[:8]) or "未发现项目内调用方"
        return (
            f"`{path}` 的职责依据静态结构生成：包含符号 {symbol_text}；"
            f"依赖 {dependency_text}；被 {caller_text} 引用。"
        )

    @staticmethod
    def _check_cancelled(state: CodeAnalysisState) -> None:
        token = state.get("cancellation_token")
        if token is not None:
            token.raise_if_cancelled()

    @staticmethod
    def _serialize_file(parsed: Any) -> dict[str, Any]:
        """把 AST 领域对象转换为图状态中的普通结构。"""

        return {
            "absolute_path": str(parsed.absolute_path),
            "relative_path": parsed.relative_path,
            "source_text": parsed.source_text,
            "external_imports": list(parsed.external_imports),
            "internal_imports": list(parsed.internal_imports),
            "blocks": [
                {
                    "name": block.name,
                    "block_type": block.block_type.value,
                    "line_start": block.line_start,
                    "line_end": block.line_end,
                    "code": block.code,
                    "parent_class": block.parent_class,
                    "docstring": block.docstring,
                }
                for block in parsed.blocks
            ],
        }

    @staticmethod
    def _inventory(state: CodeAnalysisState) -> list[dict[str, Any]]:
        """构造不包含源码正文的范围规划清单，控制 Prompt 大小。"""

        return [
            {
                "path": data["relative_path"],
                "symbols": [block["name"] for block in data["blocks"][:20]],
                "internal_imports": state["import_contexts"]
                .get(data["relative_path"], {})
                .get("internal_imports", []),
                "imported_by": state["import_contexts"]
                .get(data["relative_path"], {})
                .get("imported_by", []),
            }
            for data in state["prepared_files"].values()
        ]

    @staticmethod
    def _fallback_scope(inventory: list[dict[str, Any]], limit: int) -> list[str]:
        """范围模型输出无效时使用确定性、可解释的优先级。"""

        preferred = ("main.py", "app.py", "__main__.py", "router.py", "service.py")
        ranked = sorted(
            inventory,
            key=lambda item: (
                not item["path"].endswith(preferred),
                -(len(item["internal_imports"]) + len(item["imported_by"])),
                item["path"],
            ),
        )
        return [item["path"] for item in ranked[:limit]]


class CodeAnalysisMiniAgent:
    """提供项目和单文件入口，并把图输出恢复为稳定领域产物。"""

    def __init__(
        self,
        *,
        llm: BaseChatModel,
        inspector: SourceProjectInspector,
        operations: CodeAnalysisOperations,
        scan_max_files: int,
        source_max_bytes: int,
        max_parallelism: int = 4,
    ) -> None:
        """创建可复用的已编译图，每次调用仍使用独立状态。"""

        nodes = CodeAnalysisGraphNodes(
            llm=llm,
            inspector=inspector,
            operations=operations,
            scan_max_files=scan_max_files,
            source_max_bytes=source_max_bytes,
            max_parallelism=max_parallelism,
        )
        self._graph = build_code_analysis_graph(nodes)
        self._inspector = inspector
        self._scan_max_files = scan_max_files
        self._analysis_version = (
            f"code-analysis-v3-block-incremental:"
            f"{getattr(llm, 'model_name', type(llm).__name__)}"
        )

    def cache_identity(
        self,
        *,
        project_path: str,
        analysis_goal: str,
        mode: Literal["project", "files", "file"],
        max_files: int,
        target_file: str = "",
        target_files: list[str] | None = None,
    ) -> tuple[str, str]:
        """确定性扫描源码，并计算包含目标、范围和模型版本的精确缓存键。"""

        snapshot = self._inspector.inspect(
            project_path=Path(project_path),
            max_files=self._scan_max_files,
        )
        return snapshot.fingerprint, self._build_analysis_fingerprint(
            analysis_goal=analysis_goal,
            mode=mode,
            max_files=max_files,
            target_file=target_file,
            target_files=target_files or [],
        )

    def _build_analysis_fingerprint(
        self,
        *,
        analysis_goal: str,
        mode: Literal["project", "files", "file"],
        max_files: int,
        target_file: str,
        target_files: list[str] | None = None,
    ) -> str:
        """计算不依赖磁盘扫描的分析策略指纹。"""

        request = "|".join((
            " ".join(analysis_goal.split()), mode,
            target_file.replace("\\", "/").strip(),
            ",".join(sorted(path.replace("\\", "/").strip() for path in (target_files or []))),
            str(max_files), self._analysis_version,
        ))
        return sha256(request.encode("utf-8")).hexdigest()

    def analyze_project(
        self,
        *,
        project_path: str,
        analysis_goal: str,
        max_files: int = 8,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[ExplainedProject, dict[str, Any]]:
        """选择本地项目关键文件并生成代码块解析和项目报告。"""

        return self._run(
            project_path=project_path,
            target_file="",
            analysis_goal=analysis_goal,
            mode="project",
            max_files=max_files,
            cancellation_token=cancellation_token,
        )

    def analyze_file(
        self,
        *,
        project_path: str,
        target_file: str,
        analysis_goal: str,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[ExplainedProject, dict[str, Any]]:
        """在项目上下文中精确解析一个 Python 文件。"""

        return self._run(
            project_path=project_path,
            target_file=target_file,
            analysis_goal=analysis_goal,
            mode="file",
            max_files=1,
            cancellation_token=cancellation_token,
        )

    def analyze_files(
        self,
        *,
        project_path: str,
        target_files: list[str],
        analysis_goal: str,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[ExplainedProject, dict[str, Any]]:
        """在共享项目上下文中并行分析多个明确文件。"""

        normalized = list(dict.fromkeys(path.strip() for path in target_files if path.strip()))
        if not normalized:
            raise ValueError("target_files 至少需要一个文件")
        if len(normalized) > 20:
            raise ValueError("target_files 最多允许 20 个文件")
        return self._run(
            project_path=project_path,
            target_file="",
            target_files=normalized,
            analysis_goal=analysis_goal,
            mode="files",
            max_files=len(normalized),
            cancellation_token=cancellation_token,
        )

    def _run(
        self,
        *,
        project_path: str,
        target_file: str,
        analysis_goal: str,
        mode: Literal["project", "files", "file"],
        max_files: int,
        target_files: list[str] | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[ExplainedProject, dict[str, Any]]:
        """执行图，并返回领域项目和供 Agent 判断的覆盖元数据。"""

        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        analysis_fingerprint = self._build_analysis_fingerprint(
            analysis_goal=analysis_goal,
            mode=mode,
            max_files=max_files,
            target_file=target_file,
            target_files=target_files or [],
        )
        result = self._graph.invoke(
            {
                "project_path": project_path,
                "target_file": target_file,
                "target_files": target_files or [],
                "analysis_goal": analysis_goal,
                "mode": mode,
                "max_files": max_files,
                "cancellation_token": cancellation_token,
            }
        )
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        files = [self._restore_file(item) for item in result.get("explained_files", [])]
        if not files:
            raise RuntimeError("代码分析未生成任何可用文件结果")
        project = ExplainedProject(
            project_name=result["project_name"],
            project_path=str(result["snapshot"].project_root),
            fingerprint=result["fingerprint"],
            status=(
                ExplanationProjectStatus.COMPLETED
                if result["completion_status"] == "completed"
                else ExplanationProjectStatus.STALE
            ),
            analysis_fingerprint=analysis_fingerprint,
            files=files,
            project_summary=result["project_summary"],
        )
        metadata = {
            "mode": mode,
            "selected_paths": result["requested_paths"],
            "failed_paths": result.get("failed_paths", []),
            "errors": result.get("errors", []),
            "coverage": result["coverage"],
            "structure_coverage": result["structure_coverage"],
            "block_coverage": result["block_coverage"],
            "expected_file_count": result["expected_file_count"],
            "expected_block_count": result["expected_block_count"],
            "completed_block_count": result["completed_block_count"],
            "completion_status": result["completion_status"],
        }
        return project, metadata

    @staticmethod
    def _restore_file(data: dict[str, Any]) -> ExplainedSourceFile:
        """把图中的普通字典恢复为代码解释领域对象。"""

        return ExplainedSourceFile(
            file_path=data["file_path"],
            relative_path=data["relative_path"],
            source_text=data["source_text"],
            file_role=data["file_role"],
            blocks=[
                CodeBlockExplanation(
                    code_name=item["name"],
                    code_type=CodeBlockType(item["block_type"]),
                    line_start=item["line_start"],
                    line_end=item["line_end"],
                    explanation=item["explanation"],
                    parent_class=item.get("parent_class", ""),
                    docstring=item.get("docstring", ""),
                    full_code=item["code"],
                )
                for item in data["blocks"]
            ],
        )
