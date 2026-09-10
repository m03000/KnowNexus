"""学习笔记领域的依赖组合模块。"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel

from study_help_agent.core.config import Settings
from study_help_agent.infrastructure.persistence import SqliteConnectionFactory
from study_help_agent.capabilities.learning_notes.llm import (
    LearningContentNormalizerOperations,
    LearningNoteBuilderOperations,
)
from study_help_agent.capabilities.learning_notes.mini_agents import (
    LearningNoteBuilderMiniAgent,
    LearningNoteBuilderNodes,
)
from study_help_agent.runtime.tools import ToolDefinition
from study_help_agent.tools import (
    create_learning_tool_groups,
)
from study_help_agent.capabilities.learning_notes.application import (
    KnowledgePointService,
    LearningNoteService,
    LearningResourceService,
)
from study_help_agent.capabilities.learning_notes.application.document_ingestion_service import (
    ImportedDocumentIngestionService,
)
from study_help_agent.capabilities.knowledge_ingestion.application.deletion_service import (
    KnowledgeDeletionService,
)
from study_help_agent.capabilities.knowledge_ingestion.application.ports import (
    KnowledgeIngestionRepository,
)
from study_help_agent.capabilities.learning_notes.infrastructure import (
    FileNoteRepository,
    LibraryCatalogRepository,
    ManagedLearningResourceAcquirer,
    MultiFormatLearningContentExtractor,
    SqliteKnowledgePointRepository,
)
from study_help_agent.capabilities.llm_wiki.application import (
    WikiBuildService,
    WikiSourceService,
)
from study_help_agent.capabilities.llm_wiki.infrastructure import SqliteWikiRepository
from study_help_agent.capabilities.llm_wiki.infrastructure.worker import WikiBuildWorker
from study_help_agent.capabilities.llm_wiki.infrastructure.obsidian_mcp import ObsidianMcpPublisher


@dataclass(frozen=True, slots=True)
class NoteComposition:
    """Learning 领域对应用组合根公开的最小装配结果。"""

    note_service: LearningNoteService
    wiki_build_worker: WikiBuildWorker
    tool_groups: tuple[tuple[ToolDefinition, ...], ...]


def compose_note(
    *,
    settings: Settings,
    llm: BaseChatModel,
    database: SqliteConnectionFactory,
    knowledge_repository: KnowledgeIngestionRepository,
    knowledge_deletion: KnowledgeDeletionService,
) -> NoteComposition:
    """创建学习笔记服务及生成、查询与修改工具。"""

    note_repository = FileNoteRepository(settings.runtime_data_directory / "notes")
    content_extractor = MultiFormatLearningContentExtractor(
        whisper_model=settings.learning_whisper_model,
        whisper_device=settings.learning_whisper_device,
        whisper_compute_type=settings.learning_whisper_compute_type,
        video_sample_seconds=settings.learning_video_sample_seconds,
        video_max_frames=settings.learning_video_max_frames,
        ocr_languages=settings.learning_ocr_languages,
        media_max_parallelism=settings.learning_media_max_parallelism,
        video_split_threshold_seconds=settings.learning_video_split_threshold_seconds,
        video_segment_seconds=settings.learning_video_segment_seconds,
        parallel_audio_visual=settings.learning_video_parallel_audio_visual,
    )
    resource_service = LearningResourceService(
        acquirer=ManagedLearningResourceAcquirer(
            storage_directory=settings.runtime_data_directory / "learning_resources",
            allowed_roots=settings.allowed_project_roots,
            max_bytes=settings.learning_resource_max_bytes,
            video_cookie_browser=settings.learning_video_cookie_browser,
        ),
        extractor=content_extractor,
    )
    point_service = KnowledgePointService(
        repository=SqliteKnowledgePointRepository(database),
        llm=llm,
    )
    wiki_repository = SqliteWikiRepository(database)
    wiki_sources = WikiSourceService(
        wiki_repository,
        settings.runtime_data_directory / "sources",
    )
    wiki_build_worker = WikiBuildWorker(
        repository=wiki_repository,
        build_service=WikiBuildService(
            repository=wiki_repository,
            point_service=point_service,
            wiki_root=settings.runtime_data_directory / "wiki",
            obsidian_publisher=ObsidianMcpPublisher(settings.runtime_data_directory / "obsidian_wiki.json"),
        ),
        poll_seconds=settings.knowledge_ingestion_poll_seconds,
        batch_size=max(1, min(settings.knowledge_ingestion_batch_size, 2)),
        max_attempts=settings.knowledge_ingestion_max_attempts,
    )
    note_service = LearningNoteService(
        repository=note_repository,
        point_service=point_service,
        catalog=LibraryCatalogRepository(
            database,
            settings.runtime_data_directory / "library_documents",
        ),
        document_ingestion=ImportedDocumentIngestionService(
            extractor=content_extractor,
            repository=knowledge_repository,
            wiki_sources=wiki_sources,
        ),
        knowledge_deletion=knowledge_deletion,
        wiki_sources=wiki_sources,
        export_directory=settings.note_export_directory,
    )

    return NoteComposition(
        note_service=note_service,
        wiki_build_worker=wiki_build_worker,
        tool_groups=(
            *create_learning_tool_groups(
                note_service=note_service,
                note_builder_mini_agent=LearningNoteBuilderMiniAgent(
                    nodes=LearningNoteBuilderNodes(
                        operations=LearningNoteBuilderOperations(llm)
                    )
                ),
                resource_service=resource_service,
                content_normalizer=LearningContentNormalizerOperations(
                    llm,
                    max_batch_characters=settings.learning_normalization_chunk_characters,
                    max_parallelism=settings.learning_normalization_max_parallelism,
                ),
            ),
        ),
    )
