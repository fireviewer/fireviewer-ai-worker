"""Additive FireViewer Part.2/Part.3 MVP contracts and deterministic baselines.

This package intentionally stops at camera poses and rays. Terrain/map building,
ray/terrain intersection and perimeter generation remain outside its boundary.
"""

from firewarning_worker.mvp.contracts import (
    DetectionResultV1,
    EventEvidenceV1,
    LocalizationResultV1,
    SatelliteResultV1,
)

__all__ = [
    "DetectionResultV1",
    "EventEvidenceV1",
    "LocalizationResultV1",
    "SatelliteResultV1",
]
