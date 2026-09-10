"""LLM Wiki 后台增量构建 Worker。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from study_help_agent.capabilities.llm_wiki.application.build_service import (
    WikiBuildService,
)
from study_help_agent.capabilities.llm_wiki.infrastructure.repository import (
    SqliteWikiRepository,
)


@dataclass(frozen=True, slots=True)
class WikiWorkerBatchResult:
    claimed: int
    completed: int
    failed: int
    pages: int


class WikiBuildWorker:
    def __init__(
        self,
        *,
        repository: SqliteWikiRepository,
        build_service: WikiBuildService,
        poll_seconds: float = 2.0,
        batch_size: int = 2,
        max_attempts: int = 3,
    ) -> None:
        self._repository = repository
        self._build_service = build_service
        self._poll_seconds = poll_seconds
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        await asyncio.to_thread(self._repository.recover_running_jobs)
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="llm-wiki-build-worker")

    async def stop(self) -> None:
        if self._task is None or self._stop_event is None:
            return
        self._stop_event.set()
        await self._task
        self._task = None
        self._stop_event = None

    async def _run(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            await asyncio.to_thread(self.run_once)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_seconds)
            except TimeoutError:
                pass

    def run_once(self) -> WikiWorkerBatchResult:
        jobs = self._repository.claim_jobs(self._batch_size)
        completed = failed = pages = 0
        for job in jobs:
            build_id = self._repository.start_build(
                str(job["source_id"]), str(job["operation"])
            )
            try:
                pages += self._build_service.process(job)
                self._repository.mark_job_completed(int(job["queue_id"]))
                usage = self._build_service.last_usage
                self._repository.finish_build(
                    build_id,
                    input_tokens=int(usage.get("input_tokens", 0)),
                    output_tokens=int(usage.get("output_tokens", 0)),
                )
                completed += 1
            except Exception as error:
                message = f"{type(error).__name__}: {error}"
                self._repository.mark_job_failed(
                    int(job["queue_id"]), message, max_attempts=self._max_attempts
                )
                self._repository.finish_build(build_id, error=message)
                failed += 1
        return WikiWorkerBatchResult(len(jobs), completed, failed, pages)
