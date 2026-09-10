"""定义知识空间、知识资产类型和入库任务状态。"""

from enum import StrEnum


class KnowledgeSpace(StrEnum):
    """隔离不同生命周期和检索策略的三个知识空间。"""

    PROJECT_CODE = "project_code"
    PERSONAL_KNOWLEDGE = "personal_knowledge"
    USER_MEMORY = "user_memory"


class KnowledgeAssetType(StrEnum):
    """描述持久化知识的业务语义，而不是原始 Artifact 的技术类型。"""

    PROJECT_REPORT = "project_report"
    MODULE_ANALYSIS = "module_analysis"
    FILE_ANALYSIS = "file_analysis"
    CODE_BLOCK_ANALYSIS = "code_block_analysis"
    LEARNING_NOTE = "learning_note"
    IMPORTED_DOCUMENT = "imported_document"
    CONVERSATION_EPISODE = "conversation_episode"
    USER_FACT = "user_fact"
    USER_PREFERENCE = "user_preference"


class IngestionStatus(StrEnum):
    """知识资产和 Outbox 任务共享的基本生命周期状态。"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    RETRYING = "retrying"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    DELETING = "deleting"
