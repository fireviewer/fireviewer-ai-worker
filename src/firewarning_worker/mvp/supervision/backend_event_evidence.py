"""Integrity-checked adapters for durable EventEvidence served by the Azure backend."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from http import HTTPStatus
from ipaddress import ip_address
from typing import Any, Literal, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import Field, SecretStr, field_validator, model_validator

from firewarning_worker.contracts import SafeIdentifierV2, Sha256HexV2, StrictModel
from firewarning_worker.mvp.contracts import (
    Claim,
    DetectionResultV1,
    EventEvidenceV1,
    EvidenceMedia,
    EvidenceSource,
    GeographicReference,
    GeospatialConsistencyCheck,
    LocationCandidate,
    PointAssessmentV1,
    PointEvidenceBundleV1,
    PriorFireStateReference,
    SatelliteObservation,
    UploadLocationEvidence,
    VisualObservation,
)
from firewarning_worker.mvp.contracts.common import TimeWindow, is_timezone_aware
from firewarning_worker.mvp.supervision.point_supervisor import PointSupervisorInputImage

_SNAPSHOT_SCHEMA = "event-evidence-read-1.0"
_SNAPSHOT_PATH = "/api/v1/internal/event-evidence/{candidate_id}"
_ASSET_PATH = "/api/v1/internal/event-evidence/{candidate_id}/assets/{asset_id}/content"
_VISUAL_EVIDENCE_PATH = "/api/v1/internal/event-evidence/{candidate_id}/visual-observations"
_RESEARCH_EVIDENCE_PATH = "/api/v1/internal/event-evidence/{candidate_id}/research-pages"
_POINT_ASSESSMENT_PATH = "/api/v1/internal/event-evidence/{candidate_id}/point-assessments"
_DEFAULT_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class BackendEventEvidenceError(RuntimeError):
    """The durable backend evidence could not be read or verified."""


class BackendEventEvidenceNotFoundError(BackendEventEvidenceError, KeyError):
    """The requested backend EventEvidence does not exist."""


class BackendViewpoint(StrictModel):
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    horizontal_accuracy_m: float = Field(gt=0, le=100_000, allow_inf_nan=False)
    altitude_m: float | None = None
    label: str | None = None
    yaw_deg: float | None = Field(default=None, ge=0, lt=360)
    fov_deg: float | None = Field(default=None, gt=0, lt=180)
    origin: str = Field(min_length=1, max_length=64)


class BackendObservedTime(StrictModel):
    start_at: datetime
    end_at: datetime | None = None

    @model_validator(mode="after")
    def validate_time(self) -> BackendObservedTime:
        if not is_timezone_aware(self.start_at):
            raise ValueError("backend observed time must include a timezone")
        if self.end_at is not None:
            if not is_timezone_aware(self.end_at):
                raise ValueError("backend observed end must include a timezone")
            if self.end_at < self.start_at:
                raise ValueError("backend observed end precedes its start")
        return self


class BackendEvidenceAsset(StrictModel):
    evidence_asset_id: SafeIdentifierV2
    kind: str = Field(pattern=r"^(image|video)$")
    declared_media_type: str = Field(min_length=1, max_length=128)
    detected_media_type: str | None = Field(default=None, max_length=128)
    size_bytes: int = Field(gt=0)
    sha256: Sha256HexV2


class BackendConsent(StrictModel):
    analysis: bool
    retention: bool
    public_derivative: bool


class BackendProvenance(StrictModel):
    received_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)

    @field_validator("received_at")
    @classmethod
    def validate_received_at(cls, value: datetime) -> datetime:
        if not is_timezone_aware(value):
            raise ValueError("backend provenance time must include a timezone")
        return value


class BackendEventBundle(StrictModel):
    candidate_id: SafeIdentifierV2
    incident_id: SafeIdentifierV2 | None = None
    incident_candidate_id: SafeIdentifierV2 | None = None
    viewpoint: BackendViewpoint
    observed_time: BackendObservedTime
    message: str | None = Field(default=None, max_length=10_000)
    evidence_assets: tuple[BackendEvidenceAsset, ...] = Field(default=(), max_length=20)
    consent: BackendConsent
    provenance: BackendProvenance
    external_observations: tuple[dict[str, Any], ...] = Field(default=(), max_length=2_048)


class BackendTerrainReference(StrictModel):
    terrain_id: SafeIdentifierV2
    package_id: SafeIdentifierV2
    file_id: int = Field(ge=1)
    sha256: Sha256HexV2
    size_bytes: int = Field(gt=0, le=1_073_741_824)
    media_type: Literal["application/vnd.fireviewer.terrain"]
    crs: str = Field(min_length=4, max_length=128)
    resolution_m: float = Field(gt=0, le=10_000)
    content_path: str = Field(
        pattern=r"^/api/v1/internal/event-evidence/[A-Za-z0-9._:-]+/terrain/content$",
        max_length=512,
    )


class BackendLocalizationAttempt(StrictModel):
    attempt_id: SafeIdentifierV2
    state: str = Field(min_length=1, max_length=64)
    method: str = Field(min_length=1, max_length=128)
    model_id: str | None = Field(default=None, max_length=500)
    model_revision: str | None = Field(default=None, max_length=255)
    view_profile: str = Field(min_length=1, max_length=64)
    anchor: dict[str, Any] = Field(default_factory=dict)
    geometry: dict[str, Any] | None = None
    uncertainty: dict[str, Any] | None = None
    horizontal_uncertainty_m: float | None = Field(default=None, gt=0, le=100_000)
    abstention_reason: str | None = Field(default=None, max_length=1_000)
    provenance: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def validate_updated_at(cls, value: datetime) -> datetime:
        if not is_timezone_aware(value):
            raise ValueError("backend localization time must include a timezone")
        return value


class BackendPriorFireActivityEvent(StrictModel):
    event_id: SafeIdentifierV2
    state: str = Field(min_length=1, max_length=64)
    phenomenon_kind: str = Field(min_length=1, max_length=64)
    observed_start_at: datetime
    observed_end_at: datetime | None = None
    geometry: dict[str, Any]
    uncertainty: dict[str, Any]
    method: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    updated_at: datetime

    @model_validator(mode="after")
    def validate_times(self) -> BackendPriorFireActivityEvent:
        values = (self.observed_start_at, self.observed_end_at, self.updated_at)
        if any(value is not None and not is_timezone_aware(value) for value in values):
            raise ValueError("backend prior fire state times must include a timezone")
        return self


class BackendPersistedVisualObservation(StrictModel):
    observation_id: SafeIdentifierV2
    media_id: SafeIdentifierV2
    observation_type: str = Field(pattern=r"^detection$")
    result_reference: SafeIdentifierV2
    confidence: float | None = Field(default=None, ge=0, le=1)
    result: DetectionResultV1

    @model_validator(mode="after")
    def validate_result_media(self) -> BackendPersistedVisualObservation:
        if self.result.media_id != self.media_id:
            raise ValueError("backend visual result references another media item")
        expected_confidence = max(
            (item.score for item in self.result.detections),
            default=None,
        )
        if self.confidence != expected_confidence:
            raise ValueError("backend visual confidence differs from its detections")
        return self


class BackendVisualEvidence(StrictModel):
    schema_version: str = Field(pattern=r"^visual-evidence-1\.0$")
    candidate_id: SafeIdentifierV2
    source_revision_sha256: Sha256HexV2
    observations: tuple[BackendPersistedVisualObservation, ...] = Field(
        default=(),
        max_length=4_096,
    )
    request_sha256: Sha256HexV2
    persisted_at: datetime

    @model_validator(mode="after")
    def validate_visual_evidence(self) -> BackendVisualEvidence:
        if not is_timezone_aware(self.persisted_at):
            raise ValueError("backend visual persistence time must include a timezone")
        for label, identifiers in (
            ("observation", [item.observation_id for item in self.observations]),
            ("result", [item.result_reference for item in self.observations]),
            ("media", [item.media_id for item in self.observations]),
        ):
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"duplicate backend visual {label} identifier")
        return self


class BackendResearchSource(EvidenceSource):
    content_sha256: Sha256HexV2


class BackendResearchMedia(EvidenceMedia):
    source_url: str = Field(min_length=8, max_length=2_048)
    content_type: str = Field(min_length=3, max_length=128)
    size_bytes: int = Field(gt=0, le=64 * 1_024 * 1_024)


class BackendResearchPage(StrictModel):
    page_id: SafeIdentifierV2
    page_number: int = Field(ge=1, le=10_000)
    cursor: str | None = Field(default=None, max_length=2_048)
    next_cursor: str | None = Field(default=None, max_length=2_048)
    completed: bool
    request_sha256: Sha256HexV2
    duplicate_counts: tuple[int, int, int]
    persisted_at: datetime

    @model_validator(mode="after")
    def validate_page(self) -> BackendResearchPage:
        if any(value < 0 for value in self.duplicate_counts):
            raise ValueError("backend research duplicate counts cannot be negative")
        if not is_timezone_aware(self.persisted_at):
            raise ValueError("backend research persistence time must include a timezone")
        return self


class BackendResearchRetentionPolicy(StrictModel):
    raw_scraped_content_stored: Literal[False]
    articles_stored: Literal[False]
    transcripts_stored: Literal[False]
    public_media_binaries_stored: Literal[False]
    satellite_binaries_allowed: Literal[True]
    perimeter_tiles_allowed: Literal[True]
    user_media_requires_republication_consent: Literal[True]


class BackendResearchJournalEntry(StrictModel):
    entry_id: SafeIdentifierV2
    stage: str = Field(min_length=1, max_length=64)
    outcome: str = Field(min_length=1, max_length=64)
    error_code: str | None = Field(default=None, min_length=1, max_length=128)
    detail: str = Field(min_length=1, max_length=1_000)
    source_url: str | None = Field(default=None, min_length=8, max_length=2_048)
    occurred_at: datetime
    retryable: bool
    provider_id: str | None = Field(default=None, min_length=1, max_length=128)
    model_revision: str | None = Field(default=None, min_length=1, max_length=255)
    prompt_revision: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_time(self) -> BackendResearchJournalEntry:
        if not is_timezone_aware(self.occurred_at):
            raise ValueError("backend research journal time must include a timezone")
        return self


class BackendResearchEvidence(StrictModel):
    schema_version: str = Field(pattern=r"^research-evidence-1\.0$")
    candidate_id: SafeIdentifierV2
    plan_id: SafeIdentifierV2
    plan_revision: Sha256HexV2
    pages: tuple[BackendResearchPage, ...] = Field(default=(), max_length=10_000)
    sources: tuple[BackendResearchSource, ...] = Field(default=(), max_length=512)
    claims: tuple[Claim, ...] = Field(default=(), max_length=2_048)
    media: tuple[BackendResearchMedia, ...] = Field(default=(), max_length=2_048)
    journal_entries: tuple[BackendResearchJournalEntry, ...] = Field(
        default=(),
        max_length=10_000,
    )
    retention_policy: BackendResearchRetentionPolicy
    completed: bool
    next_cursor: str | None = Field(default=None, max_length=2_048)

    @model_validator(mode="after")
    def validate_research(self) -> BackendResearchEvidence:
        if self.completed and self.next_cursor is not None:
            raise ValueError("completed backend research cannot expose a next cursor")
        page_ids = [item.page_id for item in self.pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError("duplicate backend research page identifier")
        source_ids = {item.source_id for item in self.sources}
        if len(source_ids) != len(self.sources):
            raise ValueError("duplicate backend research source identifier")
        if any(item.source_id not in source_ids for item in self.claims) or any(
            item.source_id not in source_ids for item in self.media
        ):
            raise ValueError("backend research evidence references an unknown source")
        journal_ids = [item.entry_id for item in self.journal_entries]
        if len(journal_ids) != len(set(journal_ids)):
            raise ValueError("duplicate backend research journal identifier")
        return self


class BackendEventEvidenceSnapshot(StrictModel):
    schema_version: str = Field(pattern=r"^event-evidence-read-1\.0$")
    candidate_id: SafeIdentifierV2
    candidate_revision: int = Field(ge=1)
    candidate_state: str = Field(min_length=1, max_length=64)
    updated_at: datetime
    bundle: BackendEventBundle
    visual_evidence: BackendVisualEvidence | None = None
    research_evidence: BackendResearchEvidence | None = None
    localization_attempts: tuple[BackendLocalizationAttempt, ...] = Field(
        default=(),
        max_length=512,
    )
    prior_fire_activity_events: tuple[BackendPriorFireActivityEvent, ...] = Field(
        default=(),
        max_length=512,
    )
    terrain_reference: BackendTerrainReference | None = None
    analysis_result_sha256: Sha256HexV2 | None = None
    source_sha256: Sha256HexV2

    @model_validator(mode="after")
    def validate_snapshot(self) -> BackendEventEvidenceSnapshot:
        if self.schema_version != _SNAPSHOT_SCHEMA:
            raise ValueError("unsupported backend EventEvidence snapshot schema")
        if not is_timezone_aware(self.updated_at):
            raise ValueError("backend snapshot time must include a timezone")
        if self.bundle.candidate_id != self.candidate_id:
            raise ValueError("backend snapshot candidate mismatch")
        if (
            self.visual_evidence is not None
            and self.visual_evidence.candidate_id != self.candidate_id
        ):
            raise ValueError("backend visual evidence candidate mismatch")
        if (
            self.research_evidence is not None
            and self.research_evidence.candidate_id != self.candidate_id
        ):
            raise ValueError("backend research evidence candidate mismatch")
        if not self.bundle.consent.analysis or not self.bundle.consent.retention:
            raise ValueError("backend snapshot lacks analysis or retention consent")
        asset_ids = [item.evidence_asset_id for item in self.bundle.evidence_assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("duplicate backend EventEvidence asset")
        attempt_ids = [item.attempt_id for item in self.localization_attempts]
        if len(attempt_ids) != len(set(attempt_ids)):
            raise ValueError("duplicate backend localization attempt")
        return self


class AzureBackendEventEvidenceConfig(StrictModel):
    base_url: str = Field(min_length=8, max_length=2_048)
    bearer_token: SecretStr = Field(min_length=32, max_length=4_096)
    timeout_seconds: float = Field(default=10, ge=1, le=30)
    max_response_bytes: int = Field(
        default=_DEFAULT_MAX_RESPONSE_BYTES,
        ge=64 * 1024,
        le=20 * 1024 * 1024,
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.hostname is None
        ):
            raise ValueError("backend base URL must be an origin without credentials or query")
        if parsed.scheme == "https":
            return normalized
        try:
            loopback = parsed.scheme == "http" and ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.scheme == "http" and parsed.hostname == "localhost"
        if not loopback:
            raise ValueError("remote backend EventEvidence access requires HTTPS")
        return normalized


@dataclass(frozen=True, slots=True)
class BackendJsonResponse:
    payload: dict[str, Any]
    headers: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class BackendBinaryResponse:
    content: bytes
    content_type: str
    headers: Mapping[str, str]


class BackendEventEvidenceTransport(Protocol):
    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> BackendJsonResponse: ...


class BackendEvidenceMediaTransport(Protocol):
    def get_bytes(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> BackendBinaryResponse: ...


class BackendVisualEvidenceTransport(Protocol):
    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> BackendJsonResponse: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class UrllibBackendEventEvidenceTransport:
    """Small dependency-free HTTPS transport with bounded, no-redirect reads."""

    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> BackendJsonResponse:
        request = Request(url, headers=dict(headers), method="GET")  # noqa: S310
        try:
            with build_opener(_NoRedirectHandler()).open(
                request,
                timeout=timeout_seconds,
            ) as response:
                content_type = response.headers.get_content_type()
                if content_type != "application/json":
                    raise BackendEventEvidenceError("backend response is not JSON")
                raw_length = response.headers.get("content-length")
                if raw_length is not None and int(raw_length) > max_response_bytes:
                    raise BackendEventEvidenceError("backend response exceeds the size limit")
                body = response.read(max_response_bytes + 1)
                if len(body) > max_response_bytes:
                    raise BackendEventEvidenceError("backend response exceeds the size limit")
                response_headers = {
                    key.casefold(): value for key, value in response.headers.items()
                }
        except HTTPError as exc:
            if exc.code == HTTPStatus.NOT_FOUND:
                raise BackendEventEvidenceNotFoundError(url) from exc
            raise BackendEventEvidenceError(f"backend returned HTTP {exc.code}") from exc
        except (OSError, URLError, ValueError) as exc:
            raise BackendEventEvidenceError("backend EventEvidence request failed") from exc
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackendEventEvidenceError("backend returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise BackendEventEvidenceError("backend response must be a JSON object")
        return BackendJsonResponse(payload=payload, headers=response_headers)

    def get_bytes(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> BackendBinaryResponse:
        request = Request(url, headers=dict(headers), method="GET")  # noqa: S310
        try:
            with build_opener(_NoRedirectHandler()).open(
                request,
                timeout=timeout_seconds,
            ) as response:
                raw_length = response.headers.get("content-length")
                if raw_length is not None and int(raw_length) > max_response_bytes:
                    raise BackendEventEvidenceError(
                        "backend media exceeds the size limit"
                    )
                content = response.read(max_response_bytes + 1)
                if len(content) > max_response_bytes:
                    raise BackendEventEvidenceError(
                        "backend media exceeds the size limit"
                    )
                response_headers = {
                    key.casefold(): value for key, value in response.headers.items()
                }
                content_type = response.headers.get_content_type()
        except HTTPError as exc:
            if exc.code == HTTPStatus.NOT_FOUND:
                raise BackendEventEvidenceNotFoundError(url) from exc
            raise BackendEventEvidenceError(f"backend returned HTTP {exc.code}") from exc
        except (OSError, URLError, ValueError) as exc:
            raise BackendEventEvidenceError("backend media request failed") from exc
        return BackendBinaryResponse(
            content=content,
            content_type=content_type,
            headers=response_headers,
        )

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> BackendJsonResponse:
        request_headers = {**headers, "Content-Type": "application/json"}
        request = Request(  # noqa: S310
            url,
            data=json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        try:
            with build_opener(_NoRedirectHandler()).open(
                request,
                timeout=timeout_seconds,
            ) as response:
                if response.headers.get_content_type() != "application/json":
                    raise BackendEventEvidenceError("backend response is not JSON")
                raw_length = response.headers.get("content-length")
                if raw_length is not None and int(raw_length) > max_response_bytes:
                    raise BackendEventEvidenceError("backend response exceeds the size limit")
                body = response.read(max_response_bytes + 1)
                if len(body) > max_response_bytes:
                    raise BackendEventEvidenceError("backend response exceeds the size limit")
                response_headers = {
                    key.casefold(): value for key, value in response.headers.items()
                }
        except HTTPError as exc:
            raise BackendEventEvidenceError(f"backend returned HTTP {exc.code}") from exc
        except (OSError, URLError, ValueError) as exc:
            raise BackendEventEvidenceError("backend evidence write request failed") from exc
        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackendEventEvidenceError("backend returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise BackendEventEvidenceError("backend response must be a JSON object")
        return BackendJsonResponse(payload=decoded, headers=response_headers)


@dataclass(frozen=True, slots=True)
class DurableResearchProgress:
    plan_id: str
    plan_revision: str
    page_count: int
    completed: bool
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class DurableEventEvidence:
    event: EventEvidenceV1
    media_locations: tuple[BackendEvidenceMediaLocation, ...]
    vision_artifacts: tuple[DetectionResultV1, ...]
    upload_locations: tuple[UploadLocationEvidence, ...]
    prior_fire_states: tuple[PriorFireStateReference, ...]
    geospatial_checks: tuple[GeospatialConsistencyCheck, ...]
    geographic_references: tuple[GeographicReference, ...]
    source_revision_sha256: str
    terrain_reference: DurableTerrainReference | None = None
    research_progress: DurableResearchProgress | None = None
    research_journal: tuple[BackendResearchJournalEntry, ...] = ()
    incident_id: str | None = None
    viewpoint_label: str | None = None

    def checks_for(self, candidate_id: str) -> tuple[GeospatialConsistencyCheck, ...]:
        return tuple(
            check for check in self.geospatial_checks if candidate_id in check.evidence_ids
        )


class EventEvidenceRepository(Protocol):
    def read(self, event_id: str) -> DurableEventEvidence: ...


class DurableTerrainReference(StrictModel):
    terrain_id: SafeIdentifierV2
    package_id: SafeIdentifierV2
    sha256: Sha256HexV2
    size_bytes: int = Field(gt=0, le=1_073_741_824)
    media_type: Literal["application/vnd.fireviewer.terrain"]
    crs: str = Field(min_length=4, max_length=128)
    resolution_m: float = Field(gt=0, le=10_000)
    content_url: str = Field(min_length=8, max_length=2_048)


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}-{sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _point_coordinates(geometry: dict[str, Any] | None) -> tuple[float, float] | None:
    if geometry is None or geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates")
    if (
        not isinstance(coordinates, list)
        or len(coordinates) < 2
        or not all(isinstance(value, (int, float)) for value in coordinates[:2])
    ):
        return None
    longitude, latitude = float(coordinates[0]), float(coordinates[1])
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        return None
    return longitude, latitude


def _anchor_perception(attempt: BackendLocalizationAttempt) -> dict[str, Any] | None:
    perception = attempt.anchor.get("perception")
    return perception if isinstance(perception, dict) else None


class BackendEvidenceMediaLocation(StrictModel):
    media_id: SafeIdentifierV2
    working_file_url: str = Field(min_length=8, max_length=2_048)


class BackendVisualEvidenceReceipt(StrictModel):
    candidate_id: SafeIdentifierV2
    observation_count: int = Field(ge=0)
    replayed: bool
    source_revision_sha256: Sha256HexV2


class BackendResearchEvidenceReceipt(StrictModel):
    candidate_id: SafeIdentifierV2
    plan_id: SafeIdentifierV2
    page_id: SafeIdentifierV2
    replayed: bool
    source_count: int = Field(ge=0)
    claim_count: int = Field(ge=0)
    media_count: int = Field(ge=0)
    duplicate_source_count: int = Field(ge=0)
    duplicate_claim_count: int = Field(ge=0)
    duplicate_media_count: int = Field(ge=0)
    completed: bool
    next_cursor: str | None = None
    source_revision_sha256: Sha256HexV2


class BackendPointAssessmentReceipt(StrictModel):
    schema_version: Literal["point-assessment-publication-receipt-1.0"]
    candidate_id: SafeIdentifierV2
    assessment_id: SafeIdentifierV2
    point_id: SafeIdentifierV2
    release_status: Literal[
        "eligible_for_automatic_publication",
        "held_for_review",
    ]
    publication_state: Literal["EDITOR_PUBLISHED", "HELD_FOR_REVIEW"]
    fire_activity_event_id: SafeIdentifierV2 | None = None
    localization_attempt_id: SafeIdentifierV2 | None = None
    publication_revision: int | None = Field(default=None, ge=1)
    competing_point_state: Literal["persisted_for_independent_assessment"] | None = None
    replayed: bool
    receipt_sha256: Sha256HexV2

    @model_validator(mode="after")
    def validate_publication_fields(self) -> BackendPointAssessmentReceipt:
        published = self.publication_state == "EDITOR_PUBLISHED"
        publication_fields = (
            self.fire_activity_event_id,
            self.localization_attempt_id,
            self.publication_revision,
        )
        if published != all(item is not None for item in publication_fields):
            raise ValueError("point publication receipt fields are inconsistent")
        if published != (
            self.release_status == "eligible_for_automatic_publication"
        ):
            raise ValueError("point publication receipt release status is inconsistent")
        return self


def _snapshot_to_durable(
    snapshot: BackendEventEvidenceSnapshot,
    *,
    base_url: str,
) -> DurableEventEvidence:
    source_id = _stable_id("BACKEND-SOURCE", snapshot.candidate_id)
    source = EvidenceSource(
        source_id=source_id,
        origin_id=snapshot.candidate_id,
        publisher="FireViewer backend EventEvidence",
        retrieved_at=snapshot.updated_at,
        source_type="witness",
        independence_weight=1,
    )
    claims: list[Claim] = []
    if snapshot.bundle.message:
        claims.append(
            Claim(
                claim_id=_stable_id("BACKEND-CLAIM", snapshot.bundle.message),
                source_id=source_id,
                claim_type="contributor_observation",
                text=snapshot.bundle.message,
                observed_at=snapshot.bundle.observed_time.start_at,
                confidence=1,
            )
        )
    sources: list[EvidenceSource] = [source]
    media = list(
        EvidenceMedia(
            media_id=asset.evidence_asset_id,
            source_id=source_id,
            media_group_id=_stable_id("BACKEND-GROUP", asset.evidence_asset_id),
            origin_id=asset.evidence_asset_id,
            kind="photo" if asset.kind == "image" else "video",
            sha256=asset.sha256,
            captured_at=snapshot.bundle.observed_time.start_at,
        )
        for asset in snapshot.bundle.evidence_assets
    )
    if snapshot.research_evidence is not None:
        sources.extend(
            EvidenceSource.model_validate(
                item.model_dump(mode="json", exclude={"content_sha256"})
            )
            for item in snapshot.research_evidence.sources
        )
        claims.extend(snapshot.research_evidence.claims)
        media.extend(
            EvidenceMedia.model_validate(
                item.model_dump(
                    mode="json",
                    exclude={"source_url", "content_type", "size_bytes"},
                )
            )
            for item in snapshot.research_evidence.media
        )
    media_ids = {item.media_id for item in media}

    visual_observations: list[VisualObservation] = []
    vision_artifacts: list[DetectionResultV1] = []
    if snapshot.visual_evidence is not None:
        for item in snapshot.visual_evidence.observations:
            visual_observations.append(
                VisualObservation(
                    observation_id=item.observation_id,
                    media_id=item.media_id,
                    observation_type="detection",
                    result_reference=item.result_reference,
                    confidence=item.confidence,
                )
            )
            vision_artifacts.append(item.result)
    visual_observation_ids = {item.observation_id for item in visual_observations}
    location_candidates: list[LocationCandidate] = []
    geographic_references: list[GeographicReference] = []
    satellite_observations: list[SatelliteObservation] = []
    for raw in snapshot.bundle.external_observations:
        semantic_role = raw.get("semantic_role")
        geometry = raw.get("geometry_geojson")
        phenomenon = raw.get("phenomenon")
        if (
            semantic_role not in {"raw_earth_observation", "sensor_detection"}
            or not isinstance(geometry, dict)
        ):
            continue
        reference_id = raw.get("observation_id")
        artifact_revision = raw.get("artifact_revision_id")
        lineage_family_id = raw.get("lineage_family_id")
        if not isinstance(reference_id, str) or not isinstance(artifact_revision, str):
            continue
        observed_at = raw.get("observed_at")
        resolution = raw.get("resolution_m")
        confidence = raw.get("confidence")
        reference = GeographicReference.model_validate(
            {
                "reference_id": reference_id,
                "reference_kind": (
                    "satellite_hotspot"
                    if phenomenon == "thermal_hotspot"
                    or geometry.get("type") in {"Point", "MultiPoint"}
                    else "satellite_active_area"
                ),
                "geometry_geojson": geometry,
                "observed_at": observed_at,
                "horizontal_uncertainty_m": (
                    resolution if isinstance(resolution, (int, float)) else None
                ),
                "confidence": (
                    confidence if isinstance(confidence, (int, float)) else None
                ),
                "artifact_revision": artifact_revision,
                "lineage_family_id": (
                    lineage_family_id if isinstance(lineage_family_id, str) else None
                ),
            }
        )
        geographic_references.append(reference)
        if reference.observed_at is not None:
            satellite_observations.append(
                SatelliteObservation(
                    observation_id=reference.reference_id,
                    source_id=source_id,
                    observation_type=(
                        "hotspot"
                        if reference.reference_kind == "satellite_hotspot"
                        else "change"
                    ),
                    result_reference=artifact_revision,
                    acquired_at=reference.observed_at,
                    confidence=reference.confidence,
                )
            )
    upload_locations = tuple(
        UploadLocationEvidence(
            location_id=_stable_id("UPLOAD-LOCATION", asset.evidence_asset_id),
            media_id=asset.evidence_asset_id,
            longitude=snapshot.bundle.viewpoint.longitude,
            latitude=snapshot.bundle.viewpoint.latitude,
            accuracy_m=snapshot.bundle.viewpoint.horizontal_accuracy_m,
            location_origin=(
                "metadata" if snapshot.bundle.viewpoint.origin == "DEVICE_GPS" else "user_declared"
            ),
            captured_at=snapshot.bundle.observed_time.start_at,
            heading_deg=snapshot.bundle.viewpoint.yaw_deg,
            horizontal_fov_deg=snapshot.bundle.viewpoint.fov_deg,
            heading_uncertainty_deg=(
                min(snapshot.bundle.viewpoint.fov_deg / 2, 180)
                if snapshot.bundle.viewpoint.yaw_deg is not None
                and snapshot.bundle.viewpoint.fov_deg is not None
                else None
            ),
            altitude_m=snapshot.bundle.viewpoint.altitude_m,
            altitude_uncertainty_m=(
                snapshot.bundle.viewpoint.horizontal_accuracy_m
                if snapshot.bundle.viewpoint.altitude_m is not None
                else None
            ),
            source_record_sha256=_canonical_sha256(
                {
                    "candidate_id": snapshot.candidate_id,
                    "viewpoint": snapshot.bundle.viewpoint.model_dump(mode="json"),
                    "observed_time": snapshot.bundle.observed_time.model_dump(mode="json"),
                    "asset_sha256": asset.sha256,
                }
            ),
        )
        for asset in snapshot.bundle.evidence_assets
    )

    for rank, attempt in enumerate(snapshot.localization_attempts, start=1):
        perception = _anchor_perception(attempt)
        media_id = None
        score = 0.0
        anchor_id = attempt.attempt_id
        if perception is not None:
            raw_media_id = perception.get("evidence_asset_id")
            if isinstance(raw_media_id, str) and raw_media_id in media_ids:
                media_id = raw_media_id
            raw_anchor_id = perception.get("anchor_id")
            if isinstance(raw_anchor_id, str):
                anchor_id = raw_anchor_id
            raw_score = perception.get("model_score")
            if isinstance(raw_score, (int, float)) and 0 <= raw_score <= 1:
                score = float(raw_score)
            if media_id is not None:
                observation_id = _stable_id("VISUAL", anchor_id)
                if observation_id not in visual_observation_ids:
                    visual_observations.append(
                        VisualObservation(
                            observation_id=observation_id,
                            media_id=media_id,
                            observation_type=(
                                "target_pixel"
                                if perception.get("source_point_normalized") is not None
                                else "detection"
                            ),
                            result_reference=anchor_id,
                            confidence=score,
                        )
                    )
                    visual_observation_ids.add(observation_id)
        coordinates = _point_coordinates(attempt.geometry)
        if coordinates is None or attempt.state not in {"PROPOSED", "REVIEWED", "SHADOW"}:
            continue
        longitude, latitude = coordinates
        location_candidates.append(
            LocationCandidate(
                candidate_id=attempt.attempt_id,
                longitude=longitude,
                latitude=latitude,
                radius_m=attempt.horizontal_uncertainty_m or 100_000,
                score=score,
                rank=rank,
                evidence_kind="geometric_verification",
                provider_id=_stable_id("BACKEND-MODEL", attempt.model_id or attempt.method),
                provider_version=attempt.model_revision or "unversioned-backend-result",
                source_id=source_id,
                media_id=media_id,
                reference_id=anchor_id,
            )
        )

    prior_fire_states = tuple(
        PriorFireStateReference(
            state_id=_stable_id("PRIOR-STATE", item.event_id),
            state_kind=(
                "active_points" if item.geometry.get("type") == "Point" else "situation_report"
            ),
            observed_at=item.observed_start_at,
            artifact_reference=(
                f"backend://event-evidence/{snapshot.candidate_id}/history/"
                f"{item.event_id}?revision={item.version}"
            ),
            artifact_sha256=_canonical_sha256(item.model_dump(mode="json")),
        )
        for item in snapshot.prior_fire_activity_events
    )
    for history_item in snapshot.prior_fire_activity_events:
        geometry_type = history_item.geometry.get("type")
        reference_kind: Literal[
            "prior_active_point", "prior_fire_front", "prior_perimeter"
        ]
        if history_item.phenomenon_kind in {"visible_front", "visible_fire_front"}:
            reference_kind = "prior_fire_front"
        elif geometry_type in {"Point", "MultiPoint"}:
            reference_kind = "prior_active_point"
        else:
            reference_kind = "prior_perimeter"
        geographic_references.append(
            GeographicReference(
                reference_id=_stable_id("HISTORY-GEO", history_item.event_id),
                reference_kind=reference_kind,
                geometry_geojson=history_item.geometry,
                observed_at=history_item.observed_start_at,
                artifact_revision=_canonical_sha256(history_item.model_dump(mode="json")),
            )
        )

    checks: list[GeospatialConsistencyCheck] = []
    for candidate in location_candidates:
        related_media_id = candidate.media_id
        camera_evidence = tuple(
            item for item in (candidate.candidate_id, related_media_id) if item is not None
        )
        if len(camera_evidence) >= 2:
            checks.extend(
                (
                    GeospatialConsistencyCheck(
                        check_id=_stable_id("CHECK-DISTANCE", candidate.candidate_id),
                        check_type="camera_distance",
                        status="unknown",
                        reason_code="camera_distance_pending_model_review",
                        evidence_ids=camera_evidence,
                    ),
                    GeospatialConsistencyCheck(
                        check_id=_stable_id("CHECK-BEARING", candidate.candidate_id),
                        check_type="camera_bearing",
                        status="unknown",
                        reason_code="camera_bearing_pending_model_review",
                        evidence_ids=camera_evidence,
                    ),
                )
            )
        for state in prior_fire_states:
            checks.append(
                GeospatialConsistencyCheck(
                    check_id=_stable_id(
                        "CHECK-HISTORY",
                        f"{candidate.candidate_id}:{state.state_id}",
                    ),
                    check_type="history_progression",
                    status="unknown",
                    reason_code="history_progression_pending_model_review",
                    evidence_ids=(candidate.candidate_id, state.state_id),
                )
            )

    event = EventEvidenceV1(
        event_id=snapshot.candidate_id,
        time_window=TimeWindow(
            from_at=snapshot.bundle.observed_time.start_at,
            to_at=snapshot.bundle.observed_time.end_at,
        ),
        sources=tuple(sources),
        claims=tuple(claims),
        media=tuple(media),
        visual_observations=tuple(visual_observations),
        satellite_observations=tuple(satellite_observations),
        location_candidates=tuple(location_candidates),
        needs_human_review=True,
    )
    terrain_reference = None
    if snapshot.terrain_reference is not None:
        terrain_reference = DurableTerrainReference(
            terrain_id=snapshot.terrain_reference.terrain_id,
            package_id=snapshot.terrain_reference.package_id,
            sha256=snapshot.terrain_reference.sha256,
            size_bytes=snapshot.terrain_reference.size_bytes,
            media_type=snapshot.terrain_reference.media_type,
            crs=snapshot.terrain_reference.crs,
            resolution_m=snapshot.terrain_reference.resolution_m,
            content_url=base_url + snapshot.terrain_reference.content_path,
        )
    return DurableEventEvidence(
        event=event,
        media_locations=tuple(
            BackendEvidenceMediaLocation(
                media_id=asset.evidence_asset_id,
                working_file_url=base_url
                + _ASSET_PATH.format(
                    candidate_id=quote(snapshot.candidate_id, safe=""),
                    asset_id=quote(asset.evidence_asset_id, safe=""),
                ),
            )
            for asset in snapshot.bundle.evidence_assets
        ),
        vision_artifacts=tuple(vision_artifacts),
        upload_locations=upload_locations,
        prior_fire_states=prior_fire_states,
        geospatial_checks=tuple(checks),
        geographic_references=tuple(geographic_references),
        source_revision_sha256=snapshot.source_sha256,
        terrain_reference=terrain_reference,
        research_progress=(
            DurableResearchProgress(
                plan_id=snapshot.research_evidence.plan_id,
                plan_revision=snapshot.research_evidence.plan_revision,
                page_count=len(snapshot.research_evidence.pages),
                completed=snapshot.research_evidence.completed,
                next_cursor=snapshot.research_evidence.next_cursor,
            )
            if snapshot.research_evidence is not None
            else None
        ),
        research_journal=(
            snapshot.research_evidence.journal_entries
            if snapshot.research_evidence is not None
            else ()
        ),
        incident_id=snapshot.bundle.incident_id,
        viewpoint_label=snapshot.bundle.viewpoint.label,
    )


class AzureBackendEventEvidenceAdapter:
    """Read durable backend evidence; never indexes, writes, or caches it locally."""

    def __init__(
        self,
        config: AzureBackendEventEvidenceConfig,
        *,
        transport: BackendEventEvidenceTransport | None = None,
        media_transport: BackendEvidenceMediaTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or UrllibBackendEventEvidenceTransport()
        self._media_transport = media_transport or UrllibBackendEventEvidenceTransport()

    def read(self, event_id: str) -> DurableEventEvidence:
        if not event_id or len(event_id) > 128:
            raise ValueError("event_id is invalid")
        url = self._config.base_url + _SNAPSHOT_PATH.format(
            candidate_id=quote(event_id, safe=""),
        )
        response = self._transport.get_json(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._config.bearer_token.get_secret_value()}",
            },
            timeout_seconds=self._config.timeout_seconds,
            max_response_bytes=self._config.max_response_bytes,
        )
        raw_payload = dict(response.payload)
        raw_checksum = raw_payload.pop("source_sha256", None)
        if not isinstance(raw_checksum, str) or _canonical_sha256(raw_payload) != raw_checksum:
            raise BackendEventEvidenceError("backend EventEvidence checksum mismatch")
        checksum_header = response.headers.get("x-checksum-sha256")
        etag = response.headers.get("etag")
        if checksum_header != raw_checksum or etag != f'"{raw_checksum}"':
            raise BackendEventEvidenceError("backend EventEvidence revision headers mismatch")
        snapshot = BackendEventEvidenceSnapshot.model_validate(response.payload)
        if snapshot.candidate_id != event_id:
            raise BackendEventEvidenceError("backend EventEvidence candidate mismatch")
        return _snapshot_to_durable(snapshot, base_url=self._config.base_url)

    def read_media(
        self,
        *,
        event_id: str,
        media_id: str,
        expected_sha256: str,
        maximum_bytes: int = 8 * 1_024 * 1_024,
    ) -> PointSupervisorInputImage:
        if not event_id or len(event_id) > 128 or not media_id or len(media_id) > 128:
            raise ValueError("backend media identity is invalid")
        if maximum_bytes <= 0 or maximum_bytes > 8 * 1_024 * 1_024:
            raise ValueError("backend media byte limit is invalid")
        url = self._config.base_url + _ASSET_PATH.format(
            candidate_id=quote(event_id, safe=""),
            asset_id=quote(media_id, safe=""),
        )
        response = self._media_transport.get_bytes(
            url,
            headers={
                "Accept": "image/jpeg,image/png,image/webp",
                "Authorization": f"Bearer {self._config.bearer_token.get_secret_value()}",
            },
            timeout_seconds=self._config.timeout_seconds,
            max_response_bytes=maximum_bytes,
        )
        digest = sha256(response.content).hexdigest()
        if digest != expected_sha256:
            raise BackendEventEvidenceError("backend media checksum mismatch")
        if (
            response.headers.get("x-checksum-sha256") != digest
            or response.headers.get("etag") != f'"{digest}"'
        ):
            raise BackendEventEvidenceError("backend media revision headers mismatch")
        if response.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise BackendEventEvidenceError(
                "backend media type is not accepted by the point supervisor"
            )
        accepted_content_type = cast(
            Literal["image/jpeg", "image/png", "image/webp"],
            response.content_type,
        )
        try:
            return PointSupervisorInputImage(
                media_id=media_id,
                content_type=accepted_content_type,
                sha256=digest,
                content=response.content,
            )
        except ValueError as exc:
            raise BackendEventEvidenceError(
                "backend media type is not accepted by the point supervisor"
            ) from exc


class BackendVisualEvidencePublisher:
    """Persist YOLO observations while keeping all geographic collections untouched."""

    def __init__(
        self,
        config: AzureBackendEventEvidenceConfig,
        *,
        transport: BackendVisualEvidenceTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or UrllibBackendEventEvidenceTransport()

    def publish(
        self,
        *,
        candidate_id: str,
        source_revision_sha256: str,
        observations: tuple[VisualObservation, ...],
        artifacts: Mapping[str, DetectionResultV1],
    ) -> BackendVisualEvidenceReceipt:
        payload_observations: list[dict[str, Any]] = []
        for observation in observations:
            if observation.observation_type != "detection":
                continue
            result = artifacts.get(observation.result_reference)
            if result is None or result.media_id != observation.media_id:
                raise BackendEventEvidenceError(
                    "visual observation has no matching detection artifact"
                )
            payload_observations.append(
                {
                    **observation.model_dump(mode="json"),
                    "result": result.model_dump(mode="json", by_alias=True),
                }
            )
        url = self._config.base_url + _VISUAL_EVIDENCE_PATH.format(
            candidate_id=quote(candidate_id, safe=""),
        )
        response = self._transport.post_json(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._config.bearer_token.get_secret_value()}",
            },
            payload={
                "schema_version": "visual-evidence-1.0",
                "candidate_id": candidate_id,
                "source_revision_sha256": source_revision_sha256,
                "observations": payload_observations,
            },
            timeout_seconds=self._config.timeout_seconds,
            max_response_bytes=self._config.max_response_bytes,
        )
        receipt = BackendVisualEvidenceReceipt.model_validate(response.payload)
        if receipt.candidate_id != candidate_id:
            raise BackendEventEvidenceError("backend visual evidence candidate mismatch")
        checksum = receipt.source_revision_sha256
        if (
            response.headers.get("x-checksum-sha256") != checksum
            or response.headers.get("etag") != f'"{checksum}"'
        ):
            raise BackendEventEvidenceError("backend visual evidence revision headers mismatch")
        return receipt


class BackendResearchEvidencePublisher:
    """Append one deterministic research page to the durable backend graph."""

    def __init__(
        self,
        config: AzureBackendEventEvidenceConfig,
        *,
        transport: BackendVisualEvidenceTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or UrllibBackendEventEvidenceTransport()

    def publish(
        self,
        *,
        candidate_id: str,
        payload: Mapping[str, Any],
    ) -> BackendResearchEvidenceReceipt:
        if payload.get("candidate_id") != candidate_id:
            raise BackendEventEvidenceError("research evidence candidate mismatch")
        url = self._config.base_url + _RESEARCH_EVIDENCE_PATH.format(
            candidate_id=quote(candidate_id, safe=""),
        )
        response = self._transport.post_json(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._config.bearer_token.get_secret_value()}",
            },
            payload=payload,
            timeout_seconds=self._config.timeout_seconds,
            max_response_bytes=self._config.max_response_bytes,
        )
        receipt = BackendResearchEvidenceReceipt.model_validate(response.payload)
        if receipt.candidate_id != candidate_id:
            raise BackendEventEvidenceError("backend research evidence candidate mismatch")
        checksum = receipt.source_revision_sha256
        if (
            response.headers.get("x-checksum-sha256") != checksum
            or response.headers.get("etag") != f'"{checksum}"'
        ):
            raise BackendEventEvidenceError(
                "backend research evidence revision headers mismatch"
            )
        return receipt


class BackendPointAssessmentPublisher:
    """Persist the immutable point ticket and let event-2.0 enforce publication."""

    def __init__(
        self,
        config: AzureBackendEventEvidenceConfig,
        *,
        transport: BackendVisualEvidenceTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or UrllibBackendEventEvidenceTransport()

    def publish(
        self,
        *,
        candidate_id: str,
        point_bundle: PointEvidenceBundleV1,
        assessment: PointAssessmentV1,
    ) -> BackendPointAssessmentReceipt:
        if point_bundle.event_id != candidate_id or assessment.event_id != candidate_id:
            raise BackendEventEvidenceError("point assessment candidate mismatch")
        if assessment.point_id != point_bundle.point.point_id:
            raise BackendEventEvidenceError("point assessment source point mismatch")
        url = self._config.base_url + _POINT_ASSESSMENT_PATH.format(
            candidate_id=quote(candidate_id, safe=""),
        )
        response = self._transport.post_json(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._config.bearer_token.get_secret_value()}",
            },
            payload={
                "schema_version": "point-assessment-publication-1.0",
                "point_bundle": point_bundle.model_dump(mode="json", by_alias=True),
                "assessment": assessment.model_dump(mode="json", by_alias=True),
            },
            timeout_seconds=self._config.timeout_seconds,
            max_response_bytes=self._config.max_response_bytes,
        )
        receipt = BackendPointAssessmentReceipt.model_validate(response.payload)
        if (
            receipt.candidate_id != candidate_id
            or receipt.assessment_id != assessment.assessment_id
            or receipt.point_id != assessment.point_id
            or receipt.release_status != assessment.release_status
        ):
            raise BackendEventEvidenceError("backend point assessment receipt mismatch")
        checksum = receipt.receipt_sha256
        if (
            response.headers.get("x-checksum-sha256") != checksum
            or response.headers.get("etag") != f'"{checksum}"'
        ):
            raise BackendEventEvidenceError(
                "backend point assessment receipt headers mismatch"
            )
        return receipt


__all__ = [
    "AzureBackendEventEvidenceAdapter",
    "AzureBackendEventEvidenceConfig",
    "BackendBinaryResponse",
    "BackendEventEvidenceError",
    "BackendEventEvidenceNotFoundError",
    "BackendEventEvidenceSnapshot",
    "BackendEventEvidenceTransport",
    "BackendEvidenceMediaLocation",
    "BackendEvidenceMediaTransport",
    "BackendJsonResponse",
    "BackendPointAssessmentPublisher",
    "BackendPointAssessmentReceipt",
    "BackendResearchEvidence",
    "BackendResearchEvidencePublisher",
    "BackendResearchEvidenceReceipt",
    "BackendTerrainReference",
    "BackendVisualEvidencePublisher",
    "BackendVisualEvidenceReceipt",
    "BackendVisualEvidenceTransport",
    "DurableEventEvidence",
    "DurableResearchProgress",
    "DurableTerrainReference",
    "EventEvidenceRepository",
    "UrllibBackendEventEvidenceTransport",
]
