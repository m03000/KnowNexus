"""后台轮询 Transactional Outbox 并调用索引用例。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from study_help_agent.capabilities.knowledge_ingestion.application.indexing_service import (
    KnowledgeIndexingService,
)
from study_help_agent.capabilities.knowledge_ingestion.application.ports import IngestionWorkRepository


@dataclass(frozen=True, slots=True)
class WorkerBatchResult:
    """一次轮询的处理统计，便于日志、测试和健康检查。"""

    claimed: int
    completed: int
    failed: int
    chunks: int


class KnowledgeIngestionWorker:
    """生命周期托管的单进程 Worker；阻塞模型工作在线程池中执行。"""

    def __init__(
        self,
        *,
        repository: IngestionWorkRepository,
        indexing_service: KnowledgeIndexingService,
        poll_seconds: float = 2.0,
        batch_size: int = 8,
        max_attempts: int = 5,
    ) -> None:
        self._repository = repository
        self._indexing_service = indexing_service
        self._poll_seconds = poll_seconds
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None

    async def start(self) -> None:
        """恢复异常退出留下的任务并启动后台轮询。"""

        if self._task is not None:
            return
        await asyncio.to_thread(self._repository.recover_processing_jobs)
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="knowledge-ingestion-worker")

    async def stop(self) -> None:
        """通知 Worker 停止并等待当前批次安全结束。"""

        if self._task is None or self._stop_event is None:
            return
        self._stop_event.set()
        await self._task
        self._task = None
        self._stop_event = None

    async def _run(self) -> None:
        """持续处理任务；空闲时使用可中断等待而不是阻塞 sleep。"""

        assert self._stop_event is not None
        while not self._stop_event.is_set():
            await asyncio.to_thread(self.run_once)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_seconds)
            except TimeoutError:
                pass

    def run_once(self) -> WorkerBatchResult:
        """同步处理一个批次，方便线程池调度和单元测试。"""

        jobs = self._repository.claim_jobs(limit=self._batch_size)
        completed = failed = chunks = 0
        for job in jobs:
            try:
                chunks += self._indexing_service.process(job)
                completed += 1
            except Exception as error:
                failed += 1
                self._repository.mark_failed(
                    job.job_id,
                    f"{type(error).__name__}: {error}",
                    max_attempts=self._max_attempts,
                )
        return WorkerBatchResult(
            claimed=len(jobs), completed=completed, failed=failed, chunks=chunks
        )
