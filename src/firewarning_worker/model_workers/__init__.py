"""Model-specific inference contracts shared by the production adapters."""

from firewarning_worker.model_workers.detection import (
    FIREVIEWER_DETECTOR_LABELS,
    LetterboxGeometry,
    center_letterbox,
    unletterbox,
)

__all__ = [
    "FIREVIEWER_DETECTOR_LABELS",
    "LetterboxGeometry",
    "center_letterbox",
    "unletterbox",
]
