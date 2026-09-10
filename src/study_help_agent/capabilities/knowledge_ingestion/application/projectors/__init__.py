"""把不同业务 Artifact 翻译成统一知识资产。"""

from .code_projector import CodeAnalysisProjector
from .note_projector import LearningNoteProjector
from .registry import ArtifactProjector, ArtifactProjectorRegistry

__all__ = [
    "ArtifactProjector",
    "ArtifactProjectorRegistry",
    "CodeAnalysisProjector",
    "LearningNoteProjector",
]
