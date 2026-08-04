from __future__ import annotations

import os
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from math import fmod
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from firewarning_worker.geometry_contract import validate_geojson_geometry


class EventModel(BaseModel):
    """Closed, immutable contract used at the event-analysis boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)


Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class EvidenceAssetKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"


class ViewpointOrigin(StrEnum):
    USER_PLACED = "USER_PLACED"
    DEVICE_GPS = "DEVICE_GPS"
    NAMED_PLACE = "NAMED_PLACE"
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"


class ShotScale(StrEnum):
    WIDE = "wide"
    DISTANT = "distant"
    CLOSE = "close"
    TIGHT = "tight"


class ViewProfile(StrEnum):
    GROUND_WIDE_KNOWN_VIEWPOINT = "ground_wide_known_viewpoint"
    GROUND_WIDE_NAMED_VIEWPOINT = "ground_wide_named_viewpoint"
    GROUND_DISTANT_KNOWN_VIEWPOINT = "ground_distant_known_viewpoint"
    GROUND_CLOSE_KNOWN_VIEWPOINT = "ground_close_known_viewpoint"
    GROUND_TIGHT_KNOWN_VIEWPOINT = "ground_tight_known_viewpoint"


class SemanticRole(StrEnum):
    RAW_EARTH_OBSERVATION = "raw_earth_observation"
    SENSOR_DETECTION = "sensor_detection"
    INTERPRETED_OBSERVATION = "interpreted_observation"
    OFFICIAL_INCIDENT_STATEMENT = "official_incident_statement"
    WEATHER_OBSERVATION = "weather_observation"
    WEATHER_FORECAST = "weather_forecast"
    GEOSPATIAL_REFERENCE = "geospatial_reference"
    HISTORICAL_REGISTRY = "historical_registry"
    SIMULATION = "simulation"


class PhenomenonKind(StrEnum):
    ACTIVE_FIRE_POINT = "active_fire_point"
    VISIBLE_FIRE_FRONT = "visible_fire_front"
    SMOKE_COLUMN_BASE = "smoke_column_base"
    SMOKE_ORIGIN = "smoke_origin"
    THERMAL_HOTSPOT = "thermal_hotspot"
    ACTIVITY_ENVELOPE = "activity_envelope"
    BURNED_AREA = "burned_area"
    SIMULATION = "simulation"


class LocalizationStatus(StrEnum):
    LOCALIZED = "localized"
    SECTOR = "sector"
    ABSTAINED = "abstained"


class LocalizationMethod(StrEnum):
    CAMERA_RAYCAST = "camera_raycast"
    TRIANGULATION = "triangulation"
    VIEWPOINT_SECTOR = "viewpoint_sector"
    CROSS_VIEW_RAYCAST = "cross_view_raycast"
    EXPLICIT_SOURCE_GEOMETRY = "explicit_source_geometry"


class PipelineStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    ABSTAINED = "abstained"
    FAILED = "failed"


ProposalPhenomenon = Literal[
    PhenomenonKind.ACTIVE_FIRE_POINT,
    PhenomenonKind.VISIBLE_FIRE_FRONT,
    PhenomenonKind.SMOKE_ORIGIN,
]


class Viewpoint(EventModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    horizontal_accuracy_m: float = Field(gt=0, le=100_000)
    altitude_m: float | None = Field(default=None, allow_inf_nan=False)
    label: str | None = Field(default=None, min_length=1, max_length=500)
    yaw_deg: float | None = Field(default=None, ge=0, lt=360)
    fov_deg: float | None = Field(default=None, gt=0, lt=180)
    origin: ViewpointOrigin

    @model_validator(mode="after")
    def orientation_is_complete(self) -> Viewpoint:
        if (self.yaw_deg is None) != (self.fov_deg is None):
            raise ValueError("viewpoint direction requires both yaw_deg and fov_deg")
        if self.origin == ViewpointOrigin.NAMED_PLACE and not self.label:
            raise ValueError("named viewpoints require a label")
        return self


class ObservedTime(EventModel):
    start_at: datetime
    end_at: datetime | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> ObservedTime:
        values = (self.start_at,) if self.end_at is None else (self.start_at, self.end_at)
        if any(value.tzinfo is None or value.utcoffset() is None for value in values):
            raise ValueError("event observation times must include a timezone")
        if self.end_at is not None and self.end_at < self.start_at:
            raise ValueError("event observation end must not precede its start")
        return self


class EvidenceAsset(EventModel):
    evidence_asset_id: Identifier
    kind: EvidenceAssetKind
    sha256: Sha256Hex
    object_uri: str = Field(min_length=1, max_length=2_048)
    declared_media_type: str = Field(min_length=3, max_length=255)
    size_bytes: int = Field(gt=0, le=2_147_483_648)
    working_file_url: str | None = Field(default=None, min_length=1, max_length=2_048)


class EventConsent(EventModel):
    analysis: Literal[True]
    retention: Literal[True]
    public_derivative: bool = False


class BundleProvenance(EventModel):
    received_at: datetime
    idempotency_key: Identifier
    trace_id: Identifier | None = None

    @model_validator(mode="after")
    def received_time_is_aware(self) -> BundleProvenance:
        if self.received_at.tzinfo is None or self.received_at.utcoffset() is None:
            raise ValueError("received_at must include a timezone")
        return self


class ExternalObservation(EventModel):
    observation_id: Identifier
    artifact_revision_id: Identifier
    lineage_family_id: Identifier
    semantic_role: SemanticRole
    phenomenon: PhenomenonKind | None = None
    observed_at: datetime | None = None
    geometry_geojson: dict[str, Any] | None = None
    resolution_m: float | None = Field(default=None, gt=0)
    conflicts_with: tuple[Identifier, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def validate_external_observation(self) -> ExternalObservation:
        if self.observed_at is not None and (
            self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None
        ):
            raise ValueError("external observation times must include a timezone")
        if self.geometry_geojson is not None:
            validate_geojson_geometry(self.geometry_geojson)
        if self.semantic_role == SemanticRole.WEATHER_FORECAST and self.phenomenon is not None:
            raise ValueError("a weather forecast cannot assert an observed fire phenomenon")
        if self.semantic_role == SemanticRole.SIMULATION and self.phenomenon not in {
            None,
            PhenomenonKind.SIMULATION,
        }:
            raise ValueError("simulation inputs must remain semantically marked as simulation")
        return self


class EventCandidateBundle(EventModel):
    schema_version: Literal["event-2.0"] = "event-2.0"
    candidate_id: Identifier
    incident_id: Identifier | None = None
    incident_candidate_id: Identifier | None = None
    episode_id: Identifier | None = None
    viewpoint: Viewpoint
    observed_time: ObservedTime
    shot_scale: ShotScale | None = None
    message: str | None = Field(default=None, min_length=1, max_length=100_000)
    evidence_assets: tuple[EvidenceAsset, ...] = Field(default=(), max_length=20)
    consent: EventConsent
    provenance: BundleProvenance
    external_observations: tuple[ExternalObservation, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def validate_bundle(self) -> EventCandidateBundle:
        if (self.incident_id is None) == (self.incident_candidate_id is None):
            raise ValueError("exactly one incident or private incident candidate is required")
        if not self.message and not self.evidence_assets:
            raise ValueError("an event candidate requires a message or at least one media asset")
        asset_ids = [asset.evidence_asset_id for asset in self.evidence_assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("evidence asset identifiers must be unique")
        return self


class PerceptionAnchor(EventModel):
    anchor_id: Identifier
    evidence_asset_id: Identifier
    phenomenon: Literal[
        PhenomenonKind.ACTIVE_FIRE_POINT,
        PhenomenonKind.VISIBLE_FIRE_FRONT,
        PhenomenonKind.SMOKE_COLUMN_BASE,
    ]
    source_point_normalized: tuple[float, float] | None = None
    source_geometry_normalized: dict[str, Any] | None = None
    model_id: str = Field(min_length=1, max_length=500)
    model_revision: str = Field(min_length=1, max_length=255)
    model_score: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_anchor(self) -> PerceptionAnchor:
        if (self.source_point_normalized is None) == (self.source_geometry_normalized is None):
            raise ValueError("a perception anchor requires exactly one pixel point or geometry")
        if self.source_point_normalized is not None and any(
            coordinate < 0 or coordinate > 1 for coordinate in self.source_point_normalized
        ):
            raise ValueError("source point coordinates must be normalized")
        if self.source_geometry_normalized is not None:
            allowed = (
                {"LineString", "MultiLineString"}
                if self.phenomenon == PhenomenonKind.VISIBLE_FIRE_FRONT
                else {"Point"}
            )
            validate_geojson_geometry(
                self.source_geometry_normalized,
                allowed_types=allowed,
                normalized=True,
            )
        return self


class SpatialEvidence(EventModel):
    anchor_id: Identifier
    status: Literal["projected", "insufficient_geometry"]
    method: LocalizationMethod | None = None
    geometry_geojson: dict[str, Any] | None = None
    horizontal_accuracy_m: float | None = Field(default=None, gt=0, le=100_000)
    direction_uncertainty_deg: float | None = Field(default=None, ge=0, le=180)
    distance_uncertainty_m: float | None = Field(default=None, ge=0, le=100_000)
    reason_codes: tuple[str, ...] = Field(default=(), max_length=32)
    reference_revision: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_spatial_evidence(self) -> SpatialEvidence:
        if self.status == "projected":
            if self.method is None or self.geometry_geojson is None:
                raise ValueError("projected spatial evidence requires a method and geometry")
            if self.horizontal_accuracy_m is None:
                raise ValueError("projected spatial evidence requires horizontal accuracy")
            validate_geojson_geometry(self.geometry_geojson)
        elif not self.reason_codes:
            raise ValueError("insufficient spatial evidence requires a reason code")
        return self


class SectorEstimate(EventModel):
    bearing_deg: float = Field(ge=0, lt=360)
    angular_uncertainty_deg: float = Field(gt=0, le=180)
    distance_min_m: float = Field(default=0, ge=0)
    distance_max_m: float | None = Field(default=None, gt=0)


class LocalizationAttempt(EventModel):
    attempt_id: Identifier
    anchor_id: Identifier | None = None
    phenomenon: PhenomenonKind | None = None
    status: LocalizationStatus
    method: LocalizationMethod | None = None
    geometry_geojson: dict[str, Any] | None = None
    sector: SectorEstimate | None = None
    horizontal_accuracy_m: float | None = None
    direction_uncertainty_deg: float | None = None
    distance_uncertainty_m: float | None = None
    reason_codes: tuple[str, ...] = Field(default=(), max_length=32)
    model_id: str | None = None
    model_revision: str | None = None
    reference_revision: str | None = None
    shadow_only: bool = False

    @model_validator(mode="after")
    def validate_attempt(self) -> LocalizationAttempt:
        if self.status == LocalizationStatus.LOCALIZED and self.geometry_geojson is None:
            raise ValueError("localized attempts require geometry")
        if self.status == LocalizationStatus.SECTOR and self.sector is None:
            raise ValueError("sector attempts require sector parameters")
        if self.status == LocalizationStatus.ABSTAINED and not self.reason_codes:
            raise ValueError("abstentions require reason codes")
        if self.geometry_geojson is not None:
            validate_geojson_geometry(self.geometry_geojson)
        return self


class FireActivityProposal(EventModel):
    proposal_id: Identifier
    attempt_id: Identifier
    phenomenon: ProposalPhenomenon
    observed_time: ObservedTime
    geometry_geojson: dict[str, Any]
    horizontal_accuracy_m: float = Field(gt=0, le=100_000)
    status: Literal["DRAFT"] = "DRAFT"
    requires_human_review: Literal[True] = True

    @model_validator(mode="after")
    def validate_proposal_geometry(self) -> FireActivityProposal:
        allowed = (
            {"LineString", "MultiLineString"}
            if self.phenomenon == PhenomenonKind.VISIBLE_FIRE_FRONT
            else {"Point"}
        )
        validate_geojson_geometry(self.geometry_geojson, allowed_types=allowed)
        return self


class EventPipelineInput(EventModel):
    schema_version: Literal["event-2.0"] = "event-2.0"
    bundle: EventCandidateBundle
    perception_anchors: tuple[PerceptionAnchor, ...] = Field(default=(), max_length=512)
    spatial_evidence: tuple[SpatialEvidence, ...] = Field(default=(), max_length=512)

    @model_validator(mode="after")
    def validate_references(self) -> EventPipelineInput:
        asset_ids = {asset.evidence_asset_id for asset in self.bundle.evidence_assets}
        anchor_ids: set[str] = set()
        for anchor in self.perception_anchors:
            if anchor.evidence_asset_id not in asset_ids:
                raise ValueError("perception anchor references an unknown private evidence asset")
            if anchor.anchor_id in anchor_ids:
                raise ValueError("perception anchor identifiers must be unique")
            anchor_ids.add(anchor.anchor_id)
        spatial_anchor_ids = [item.anchor_id for item in self.spatial_evidence]
        if len(spatial_anchor_ids) != len(set(spatial_anchor_ids)):
            raise ValueError("only one spatial result is allowed for each anchor")
        if not set(spatial_anchor_ids).issubset(anchor_ids):
            raise ValueError("spatial evidence references an unknown perception anchor")
        return self


class EventPipelineOutput(EventModel):
    schema_version: Literal["event-result-2.0"] = "event-result-2.0"
    candidate_id: Identifier
    status: PipelineStatus
    view_profile: ViewProfile | None
    perception_anchors: tuple[PerceptionAnchor, ...]
    spatial_evidence: tuple[SpatialEvidence, ...]
    localization_attempts: tuple[LocalizationAttempt, ...]
    event_proposals: tuple[FireActivityProposal, ...]
    independent_external_families: tuple[Identifier, ...]
    contradictions: tuple[tuple[Identifier, Identifier], ...]
    reason_codes: tuple[str, ...]
    requires_human_review: Literal[True] = True


class PerceptionFailure(EventModel):
    """Internal, non-spatial record for one media perception abstention."""

    evidence_asset_id: Identifier | None = None
    reason_code: Identifier
    model_id: str | None = Field(default=None, min_length=1, max_length=500)
    model_revision: str | None = Field(default=None, min_length=1, max_length=255)


def event_pipeline_enabled() -> bool:
    return os.getenv("FV_AGENT_EVENT_PIPELINE_ENABLED", "false").strip().lower() == "true"


def classify_view_profile(bundle: EventCandidateBundle) -> ViewProfile | None:
    if bundle.shot_scale is None:
        return None
    if bundle.shot_scale == ShotScale.WIDE:
        if bundle.viewpoint.origin == ViewpointOrigin.NAMED_PLACE:
            return ViewProfile.GROUND_WIDE_NAMED_VIEWPOINT
        return ViewProfile.GROUND_WIDE_KNOWN_VIEWPOINT
    if bundle.shot_scale == ShotScale.DISTANT:
        return ViewProfile.GROUND_DISTANT_KNOWN_VIEWPOINT
    if bundle.shot_scale == ShotScale.CLOSE:
        return ViewProfile.GROUND_CLOSE_KNOWN_VIEWPOINT
    return ViewProfile.GROUND_TIGHT_KNOWN_VIEWPOINT


def source_can_seed_private_incident(role: SemanticRole) -> bool:
    """Only an official statement may seed a private matching dossier."""

    return role == SemanticRole.OFFICIAL_INCIDENT_STATEMENT


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _bearing(viewpoint: Viewpoint, anchor: PerceptionAnchor) -> SectorEstimate | None:
    if viewpoint.yaw_deg is None or viewpoint.fov_deg is None:
        return None
    if anchor.source_point_normalized is None:
        return None
    x, _ = anchor.source_point_normalized
    bearing = fmod(viewpoint.yaw_deg + (x - 0.5) * viewpoint.fov_deg + 360.0, 360.0)
    return SectorEstimate(
        bearing_deg=bearing,
        angular_uncertainty_deg=max(viewpoint.fov_deg * 0.05, 1.0),
    )


def _output_phenomenon(anchor: PerceptionAnchor) -> ProposalPhenomenon:
    if anchor.phenomenon == PhenomenonKind.SMOKE_COLUMN_BASE:
        return PhenomenonKind.SMOKE_ORIGIN
    if anchor.phenomenon == PhenomenonKind.VISIBLE_FIRE_FRONT:
        return PhenomenonKind.VISIBLE_FIRE_FRONT
    return PhenomenonKind.ACTIVE_FIRE_POINT


def _external_summary(
    observations: tuple[ExternalObservation, ...],
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    families = tuple(sorted({item.lineage_family_id for item in observations}))
    known_ids = {item.observation_id for item in observations}
    pairs: set[tuple[str, str]] = set()
    for item in observations:
        for other in item.conflicts_with:
            if other in known_ids and other != item.observation_id:
                first, second = sorted((item.observation_id, other))
                pairs.add((first, second))
    return families, tuple(sorted(pairs))


class DeterministicEventPipeline:
    """Turns evidence into review proposals without inventing spatial facts.

    Perception models only provide pixel anchors. Geographic geometry is accepted
    exclusively from deterministic spatial evidence. Cross-view remains shadow
    evidence until an independent benchmark authorizes its promotion.
    """

    def run(
        self,
        value: EventPipelineInput,
        *,
        perception_failures: tuple[PerceptionFailure, ...] = (),
    ) -> EventPipelineOutput:
        spatial_by_anchor = {item.anchor_id: item for item in value.spatial_evidence}
        attempts: list[LocalizationAttempt] = []
        proposals: list[FireActivityProposal] = []

        for anchor in value.perception_anchors:
            spatial = spatial_by_anchor.get(anchor.anchor_id)
            attempt_id = _stable_id("LOC", value.bundle.candidate_id, anchor.anchor_id)
            phenomenon = _output_phenomenon(anchor)
            if spatial is not None and spatial.status == "projected":
                if (
                    spatial.method
                    in {
                        LocalizationMethod.CAMERA_RAYCAST,
                        LocalizationMethod.CROSS_VIEW_RAYCAST,
                    }
                    and spatial.reference_revision is None
                ):
                    attempts.append(
                        LocalizationAttempt(
                            attempt_id=attempt_id,
                            anchor_id=anchor.anchor_id,
                            phenomenon=phenomenon,
                            status=LocalizationStatus.ABSTAINED,
                            method=spatial.method,
                            reason_codes=("camera_pose_or_reference_missing",),
                            model_id=anchor.model_id,
                            model_revision=anchor.model_revision,
                        )
                    )
                    continue
                if spatial.method == LocalizationMethod.CROSS_VIEW_RAYCAST:
                    attempts.append(
                        LocalizationAttempt(
                            attempt_id=attempt_id,
                            anchor_id=anchor.anchor_id,
                            phenomenon=phenomenon,
                            status=LocalizationStatus.ABSTAINED,
                            method=spatial.method,
                            reason_codes=("cross_view_shadow_only",),
                            model_id=anchor.model_id,
                            model_revision=anchor.model_revision,
                            reference_revision=spatial.reference_revision,
                            shadow_only=True,
                        )
                    )
                    continue
                assert spatial.geometry_geojson is not None
                assert spatial.horizontal_accuracy_m is not None
                geometry_type = spatial.geometry_geojson.get("type")
                front_geometry_insufficient = (
                    phenomenon == PhenomenonKind.VISIBLE_FIRE_FRONT
                    and geometry_type not in {"LineString", "MultiLineString"}
                )
                attempt = LocalizationAttempt(
                    attempt_id=attempt_id,
                    anchor_id=anchor.anchor_id,
                    phenomenon=phenomenon,
                    status=LocalizationStatus.LOCALIZED,
                    method=spatial.method,
                    geometry_geojson=spatial.geometry_geojson,
                    horizontal_accuracy_m=spatial.horizontal_accuracy_m,
                    direction_uncertainty_deg=spatial.direction_uncertainty_deg,
                    distance_uncertainty_m=spatial.distance_uncertainty_m,
                    model_id=anchor.model_id,
                    model_revision=anchor.model_revision,
                    reference_revision=spatial.reference_revision,
                    reason_codes=(
                        ("front_geometry_insufficient",) if front_geometry_insufficient else ()
                    ),
                )
                attempts.append(attempt)
                if front_geometry_insufficient:
                    # A single front point is valid pixel/localization evidence, but
                    # it cannot be promoted into a geometrically invalid front event.
                    continue
                proposals.append(
                    FireActivityProposal(
                        proposal_id=_stable_id("EVP", value.bundle.candidate_id, anchor.anchor_id),
                        attempt_id=attempt_id,
                        phenomenon=phenomenon,
                        observed_time=value.bundle.observed_time,
                        geometry_geojson=spatial.geometry_geojson,
                        horizontal_accuracy_m=spatial.horizontal_accuracy_m,
                    )
                )
                continue

            sector = _bearing(value.bundle.viewpoint, anchor)
            if sector is not None:
                attempts.append(
                    LocalizationAttempt(
                        attempt_id=attempt_id,
                        anchor_id=anchor.anchor_id,
                        phenomenon=phenomenon,
                        status=LocalizationStatus.SECTOR,
                        method=LocalizationMethod.VIEWPOINT_SECTOR,
                        sector=sector,
                        reason_codes=("distance_unknown",),
                        model_id=anchor.model_id,
                        model_revision=anchor.model_revision,
                    )
                )
            else:
                reason_codes = (
                    spatial.reason_codes
                    if spatial is not None
                    else ("direction_and_distance_missing",)
                )
                attempts.append(
                    LocalizationAttempt(
                        attempt_id=attempt_id,
                        anchor_id=anchor.anchor_id,
                        phenomenon=phenomenon,
                        status=LocalizationStatus.ABSTAINED,
                        reason_codes=reason_codes,
                        model_id=anchor.model_id,
                        model_revision=anchor.model_revision,
                    )
                )

        for failure in perception_failures:
            suffix = failure.evidence_asset_id or failure.reason_code
            attempts.append(
                LocalizationAttempt(
                    attempt_id=_stable_id(
                        "LOC",
                        value.bundle.candidate_id,
                        "perception-failure",
                        suffix,
                        failure.reason_code,
                    ),
                    status=LocalizationStatus.ABSTAINED,
                    reason_codes=(failure.reason_code,),
                    model_id=failure.model_id,
                    model_revision=failure.model_revision,
                )
            )

        if not attempts:
            attempts.append(
                LocalizationAttempt(
                    attempt_id=_stable_id("LOC", value.bundle.candidate_id, "no-anchor"),
                    status=LocalizationStatus.ABSTAINED,
                    reason_codes=("no_visual_anchor",),
                )
            )

        external_families, contradictions = _external_summary(value.bundle.external_observations)
        has_reviewable = bool(proposals) or any(
            attempt.status in {LocalizationStatus.LOCALIZED, LocalizationStatus.SECTOR}
            for attempt in attempts
        )
        status = PipelineStatus.NEEDS_REVIEW if has_reviewable else PipelineStatus.ABSTAINED
        reason_code_set = {code for attempt in attempts for code in attempt.reason_codes}
        view_profile = classify_view_profile(value.bundle)
        if view_profile is None:
            reason_code_set.add("view_profile_unclassified")
        reason_codes = tuple(sorted(reason_code_set))
        return EventPipelineOutput(
            candidate_id=value.bundle.candidate_id,
            status=status,
            view_profile=view_profile,
            perception_anchors=value.perception_anchors,
            spatial_evidence=value.spatial_evidence,
            localization_attempts=tuple(attempts),
            event_proposals=tuple(proposals),
            independent_external_families=external_families,
            contradictions=contradictions,
            reason_codes=reason_codes,
        )


class ActivityEnvelopeCandidate(EventModel):
    geometry_geojson: dict[str, Any]
    support_attempt_ids: tuple[Identifier, ...] = Field(min_length=2, max_length=512)

    @model_validator(mode="after")
    def polygon_only(self) -> ActivityEnvelopeCandidate:
        validate_geojson_geometry(
            self.geometry_geojson,
            allowed_types={"Polygon", "MultiPolygon"},
        )
        if len(set(self.support_attempt_ids)) != len(self.support_attempt_ids):
            raise ValueError("activity envelope support attempts must be unique")
        return self


def validate_activity_envelope_supports(
    candidate: ActivityEnvelopeCandidate,
    attempts: tuple[LocalizationAttempt, ...],
) -> None:
    by_id = {attempt.attempt_id: attempt for attempt in attempts}
    if not set(candidate.support_attempt_ids).issubset(by_id):
        raise ValueError("activity envelope references an unknown localization attempt")
    supports = [by_id[item] for item in candidate.support_attempt_ids]
    if any(item.status != LocalizationStatus.LOCALIZED for item in supports):
        raise ValueError("activity envelope supports must be localized")
    observed = {item.phenomenon for item in supports}
    if observed.issubset({PhenomenonKind.SMOKE_ORIGIN, PhenomenonKind.SMOKE_COLUMN_BASE}):
        raise ValueError("smoke-only evidence cannot close an activity envelope")
    forbidden = observed.intersection(
        {PhenomenonKind.THERMAL_HOTSPOT, PhenomenonKind.BURNED_AREA, PhenomenonKind.SIMULATION}
    )
    if forbidden:
        raise ValueError("hotspots, burned areas and simulations cannot support an active envelope")


def handle_event_analysis_payload(raw_input: dict[str, Any]) -> dict[str, Any]:
    request = EventPipelineInput.model_validate(raw_input)
    return DeterministicEventPipeline().run(request).model_dump(mode="json")
