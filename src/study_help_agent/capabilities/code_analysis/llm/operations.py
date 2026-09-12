from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from hashlib import sha256
import json
from threading import Lock
from typing import Any

from langchain_core.language_models import BaseChatModel

from study_help_agent.observability.context import submit_with_trace
from study_help_agent.capabilities.code_analysis.llm.prompts import (
    build_block_batch_explanation_messages,
    build_file_context_messages,
    build_project_summary_messages,
)
from study_help_agent.capabilities.code_analysis.llm.schemas import (
    BlockBatchExplanationOutput,
    FileContextOutput,
)
from study_help_agent.capabilities.code_analysis.llm.block_batching import CodeBlockBatchPlanner
from study_help_agent.capabilities.code_analysis.domain.block_selection import (
    BlockAnalysisLevel,
    CodeBlockImportanceScorer,
    build_block_id,
)
from study_help_agent.capabilities.code_analysis.llm.contexts import ExplainState
from study_help_agent.capabilities.code_analysis.domain.models import (
    CodeBlockType,
)
from study_help_agent.capabilities.code_analysis.domain.source_analysis import (
    FileImportContext,
    ParsedCodeBlock,
)
from study_help_agent.capabilities.code_analysis.llm.cost_logging import (
    invoke_with_cost_log,
)
from study_help_agent.runtime.cancellation import AgentCancelledError, CancellationToken


class CodeAnalysisOperations:
    """代码解释的原子 LLM 操作集合。

    每个公开方法都只完成一次有边界的推理：
    1. 从 State 读取输入；
    2. 调用领域对象或 LLM；
    3. 返回需要合并到 State 的增量结果。

    节点不负责数据库、缓存、HTTP 和项目目录扫描。
    """

    def __init__(self, llm: BaseChatModel, *, max_parallelism: int = 4) -> None:
        self._llm = llm
        self._max_parallelism = max(1, max_parallelism)

        self._file_context_llm = llm.with_structured_output(
            FileContextOutput,
            method="function_calling",
            include_raw=True,
        )
        self._block_batch_llm = llm.with_structured_output(
            BlockBatchExplanationOutput,
            method="function_calling",
            include_raw=True,
        )
        self._batch_planner = CodeBlockBatchPlanner()
        self._importance_scorer = CodeBlockImportanceScorer()
        # SQLite 负责完整项目的跨进程缓存；这里缓存文件级中间结果，避免同一
        # 进程内的增量补齐和相近请求再次消耗模型。缓存键完全由输入内容决定。
        self._file_context_cache: dict[str, dict[str, Any]] = {}
        self._file_explanation_cache: dict[str, dict[str, Any]] = {}
        self._cache_lock = Lock()
        self._cache_limit = 512

    def analyze_file_context(
        self,
        state: ExplainState,
    ) -> dict[str, Any]:
        """分析一个源文件在项目中的职责。"""

        token = state.get("cancellation_token")
        self._check_cancelled(token)
        # 从state中获取文件信息
        file_path = state["current_file_path"]
        file_data = state["current_file_data"]
        relative_path = file_data["relative_path"]
        blocks = file_data["blocks"]

        # 导入关系
        import_context_data = state.get(
            "import_contexts", {},
        ).get(
            relative_path, {},
        )
        cache_key = self._cache_key({
            "kind": "file_context_v1",
            "source_text": file_data.get("source_text", ""),
            "blocks": blocks,
            "imports": import_context_data,
        })
        cached = self._cache_get(self._file_context_cache, cache_key)
        if cached is not None:
            return cached

        import_context = FileImportContext(
            external_imports=list(import_context_data.get("external_imports", [])),
            internal_imports=list(import_context_data.get("internal_imports", [])),
            imported_by=list(import_context_data.get("imported_by", [])),
        )

        # 生成符号全名。如果一个方法是 class MyClass 里的 def my_method，则显示为 MyClass.my_method。
        symbol_names = [(
                f"{block['parent_class']}.{block['name']}"
                if block.get("parent_class")
                else block["name"]
            ) for block in blocks]

        # 根据已有信息和提示词构建 System + Human Message
        messages = build_file_context_messages(
            relative_path=relative_path,
            symbol_names=symbol_names,
            import_context=import_context,
        )

        # 调用模型分析
        raw_result = invoke_with_cost_log(
            self._file_context_llm,
            messages,
            stage="file_context",
            file_path=relative_path,
        )
        self._check_cancelled(token)
        # 检查并兼容不同 LLM provider 的返回格式差异
        result = (
            raw_result
            if isinstance(
                raw_result,
                FileContextOutput,
            )
            else FileContextOutput.model_validate(
                raw_result
            )
        )

        enriched_file_data = {
            **file_data,
            "file_role": result.file_role,
            "function_roles": result.function_roles,
        }

        output = {
            "file_contexts": {
                file_path: enriched_file_data,
            }
        }
        self._cache_put(self._file_context_cache, cache_key, output)
        return output

    def summarize_project(
        self,
        state: ExplainState,
    ) -> dict[str, Any]:
        """根据全部文件职责生成项目级架构总结。"""

        token = state.get("cancellation_token")
        self._check_cancelled(token)
        file_roles: dict[str, str] = {}
        dependencies: dict[str, list[str]] = {}

        # 从 state 中获取分析信息
        for file_data in state["file_contexts"].values():
            relative_path = file_data["relative_path"]
            file_role = file_data["file_role"]
            file_roles[relative_path] = file_role
            dependencies[relative_path] = list(
                file_data.get("internal_imports", [])
            )

        # 根据已有信息构建架构总结提示词
        messages = build_project_summary_messages(
            file_roles=file_roles,
            dependencies=dependencies,
        )

        # 生成文本回答，普通llm即可
        response = invoke_with_cost_log(
            self._llm,
            messages,
            stage="project_summary",
        )
        self._check_cancelled(token)

        return {
            "project_summary": self._extract_text(response)
        }

    def explain_file(
        self,
        state: ExplainState,
    ) -> dict[str, Any]:
        """解释单个文件中的全部代码块。"""

        token = state.get("cancellation_token")
        self._check_cancelled(token)
        # 获取state中的已有信息
        file_path = state["current_file_path"]
        file_data = state["current_file_data"]
        relative_path = file_data["relative_path"]
        source_text = file_data["source_text"]
        file_role = file_data["file_role"]
        function_roles = file_data.get(
            "function_roles", {},
        )
        project_summary = state["project_summary"]
        requested_ids = set(state.get("target_block_ids") or [])
        cache_key = self._cache_key({
            "kind": "file_explanation_v2",
            "source_text": source_text,
            "file_role": file_role,
            "function_roles": function_roles,
            "project_summary": project_summary,
            "target_block_ids": sorted(requested_ids),
        })
        cached = self._cache_get(self._file_explanation_cache, cache_key)
        if cached is not None:
            return cached

        blocks = [self._restore_block(item) for item in file_data["blocks"]]
        selections = {
            build_block_id(block): self._importance_scorer.score(block)
            for block in blocks
        }
        target_blocks = [
            block for block in blocks
            if not requested_ids or build_block_id(block) in requested_ids
        ]
        expected_ids = {build_block_id(block) for block in target_blocks}
        llm_blocks = [
            block for block in target_blocks
            if selections[build_block_id(block)].level
            in {BlockAnalysisLevel.DETAILED, BlockAnalysisLevel.NORMAL}
        ]
        shared_tokens = max(1, (len(project_summary) + len(file_role)) // 3)
        explanation_by_id: dict[str, str] = {}
        batches = self._batch_planner.build(
            llm_blocks,
            shared_context_tokens=shared_tokens,
        )

        def explain_batch(batch_index, batch):
            self._check_cancelled(token)
            batch_items = []
            for block in batch.blocks:
                qualified_name = (
                    f"{block.parent_class}.{block.name}"
                    if block.parent_class else block.name
                )
                batch_items.append({
                    "block_id": build_block_id(block),
                    "function_role": function_roles.get(
                        qualified_name, function_roles.get(block.name, "")
                    ),
                    "location": f"{qualified_name} 第 {block.line_start}-{block.line_end} 行",
                    "code": block.code,
                })
            raw = invoke_with_cost_log(
                self._block_batch_llm,
                build_block_batch_explanation_messages(
                    project_summary=project_summary,
                    file_role=file_role,
                    blocks=batch_items,
                ),
                stage="block_explanation",
                file_path=relative_path,
                batch_index=batch_index,
                block_count=len(batch_items),
            )
            self._check_cancelled(token)
            result = (
                raw if isinstance(raw, BlockBatchExplanationOutput)
                else BlockBatchExplanationOutput.model_validate(raw)
            )
            return batch_index, batch_items, result

        batch_results = []
        batch_errors: list[str] = []
        if batches:
            executor = ThreadPoolExecutor(
                max_workers=min(self._max_parallelism, len(batches)),
                thread_name_prefix="code-block-llm",
            )
            futures = {}
            try:
                futures = {
                    submit_with_trace(executor, explain_batch, index, batch): index
                    for index, batch in enumerate(batches, start=1)
                }
                for future in as_completed(futures):
                    self._check_cancelled(token)
                    try:
                        batch_results.append(future.result())
                    except AgentCancelledError:
                        raise
                    except Exception as error:
                        batch_errors.append(str(error))
            finally:
                cancelled = bool(token and token.cancelled)
                if cancelled:
                    for future in futures:
                        future.cancel()
                executor.shutdown(wait=not cancelled, cancel_futures=cancelled)

        for _, batch_items, result in sorted(batch_results):
            allowed_ids = {item["block_id"] for item in batch_items}
            for item in result.blocks:
                if item.block_id in allowed_ids:
                    explanation_by_id[item.block_id] = item.explanation

        explained_blocks: list[dict[str, Any]] = []
        completed_ids: list[str] = []
        for block in target_blocks:
            block_id = build_block_id(block)
            selection = selections[block_id]
            if selection.level in {BlockAnalysisLevel.TEMPLATE, BlockAnalysisLevel.SKIP}:
                explanation = self._template_explanation(block, selection.level)
            else:
                explanation = explanation_by_id.get(block_id, "")
                if not explanation:
                    continue
            completed_ids.append(block_id)
            explained_blocks.append({
                "block_id": block_id,
                "name": block.name,
                "block_type": block.block_type.value,
                "line_start": block.line_start,
                "line_end": block.line_end,
                "code": block.code,
                "parent_class": block.parent_class,
                "docstring": block.docstring,
                "explanation": explanation,
            })


        explained_file = {
            "file_path": file_path,
            "relative_path": relative_path,
            "source_text": source_text,
            "file_role": file_role,
            "blocks": explained_blocks,
        }

        output = {
            "explained_files": [explained_file],
            "processed_files": [file_path],
            "total_blocks": len(explained_blocks),
            "completed_block_ids": completed_ids,
            "missing_block_ids": sorted(expected_ids - set(completed_ids)),
            "errors": batch_errors,
        }
        if not output["missing_block_ids"]:
            self._cache_put(self._file_explanation_cache, cache_key, output)
        return output

    @staticmethod
    def _cache_key(value: dict[str, Any]) -> str:
        """把稳定输入序列化为内容寻址缓存键。"""

        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, default=str,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def _cache_get(
        self, cache: dict[str, dict[str, Any]], key: str
    ) -> dict[str, Any] | None:
        """线程安全读取并复制结果，避免图状态反向污染缓存。"""

        with self._cache_lock:
            value = cache.get(key)
            return deepcopy(value) if value is not None else None

    def _cache_put(
        self, cache: dict[str, dict[str, Any]], key: str, value: dict[str, Any]
    ) -> None:
        """保存有界进程内缓存，超过上限时淘汰最早插入项。"""

        with self._cache_lock:
            if len(cache) >= self._cache_limit:
                cache.pop(next(iter(cache)))
            cache[key] = deepcopy(value)

    @staticmethod
    def _template_explanation(
        block: ParsedCodeBlock,
        level: BlockAnalysisLevel,
    ) -> str:
        """用 AST 已知事实描述低价值代码块，不消耗 LLM。"""

        qualified_name = (
            f"{block.parent_class}.{block.name}" if block.parent_class else block.name
        )
        detail = "结构简单，无需单独进行深度语义推理。"
        if level == BlockAnalysisLevel.SKIP:
            detail = "属于低信息量辅助代码，保留源码位置但跳过深度解释。"
        return (
            f"`{qualified_name}` 是一个 {block.block_type.value}，位于第 "
            f"{block.line_start}-{block.line_end} 行。{detail}"
        )

    @staticmethod
    def _restore_block(
        block_data: dict[str, Any],
    ) -> ParsedCodeBlock:
        """把 State 中的普通字典还原成领域对象。"""

        return ParsedCodeBlock(
            name=block_data["name"],
            block_type=CodeBlockType(block_data["block_type"]),
            line_start=block_data["line_start"],
            line_end=block_data["line_end"],
            code=block_data["code"],
            parent_class=block_data.get("parent_class", ""),
            docstring=block_data.get("docstring", ""),
        )

    @staticmethod
    def _extract_text(response: Any) -> str:
        """从 LangChain 模型响应中提取文本。"""

        content = getattr(response, "content", response)

        if isinstance(content, str):
            return content.strip()

        return str(content).strip()

    @staticmethod
    def _check_cancelled(token: CancellationToken | None) -> None:
        """在昂贵操作边界协作式停止；不会把取消误记为普通文件失败。"""

        if token is not None:
            token.raise_if_cancelled()
