"""知识资产自动入库能力的公共入口。"""

from .application.coordinator import KnowledgeIngestionCoordinator
from .domain.enums import KnowledgeAssetType, KnowledgeSpace
from .domain.models import IngestionReceipt, KnowledgeAsset, KnowledgeAssetDraft

__all__ = [
    "IngestionReceipt",
    "KnowledgeAsset",
    "KnowledgeAssetDraft",
    "KnowledgeAssetType",
    "KnowledgeIngestionCoordinator",
    "KnowledgeSpace",
]
