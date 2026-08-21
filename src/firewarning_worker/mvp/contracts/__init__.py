"""Stable public contracts for the additive FireViewer MVP."""

from firewarning_worker.mvp.contracts.common import (
    CandidateArea,
    CandidateCluster,
    LocationCandidate,
    ProviderRun,
    ScoreBreakdown,
    TimeWindow,
)
from firewarning_worker.mvp.contracts.detection_v1 import Detection, DetectionResultV1
from firewarning_worker.mvp.contracts.event_evidence_v1 import (
    Claim,
    Contradiction,
    EventEvidenceV1,
    EvidenceMedia,
    EvidenceSource,
    SatelliteObservation,
    Uncertainty,
    VisualObservation,
)
from firewarning_worker.mvp.contracts.localization_v1 import (
    CameraEvidence,
    CameraGroup,
    CameraIntrinsics,
    CameraPose,
    LocalizationResultV1,
    PoseUncertainty,
    RayUncertainty,
    TargetRay,
)
from firewarning_worker.mvp.contracts.satellite_v1 import (
    SatelliteMask,
    SatelliteResultV1,
    SatelliteScene,
)

__all__ = [
    "CameraEvidence",
    "CameraGroup",
    "CameraIntrinsics",
    "CameraPose",
    "CandidateArea",
    "CandidateCluster",
    "Claim",
    "Contradiction",
    "Detection",
    "DetectionResultV1",
    "EventEvidenceV1",
    "EvidenceMedia",
    "EvidenceSource",
    "LocalizationResultV1",
    "LocationCandidate",
    "PoseUncertainty",
    "ProviderRun",
    "RayUncertainty",
    "SatelliteMask",
    "SatelliteObservation",
    "SatelliteResultV1",
    "SatelliteScene",
    "ScoreBreakdown",
    "TargetRay",
    "TimeWindow",
    "Uncertainty",
    "VisualObservation",
]
