from __future__ import annotations

import re
from collections import defaultdict
from hashlib import sha256
from typing import TYPE_CHECKING, Literal

from firewarning_worker.contracts import (
    FactProposalV2,
    InputMetadata,
    ItemResult,
    LocationOrigin,
    ReportSectionV2,
    SituationReportDraftV2,
    SourceAnnotationV2,
    SpatialProposalV2,
    WorkerBatchItemV2,
    WorkerConsensusResultV2,
    WorkerInput,
    WorkerInputV2,
    WorkerItemResultV2,
    WorkerModelCandidateRunV2,
    WorkerModelRunV2,
    WorkerOutput,
    WorkerOutputV2,
    WorkerStageTraceV2,
)

if TYPE_CHECKING:
    from firewarning_worker.spatial_pipeline import DeterministicSpatialPipeline


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _legacy_metadata(item: WorkerBatchItemV2) -> InputMetadata:
    camera = item.camera
    if camera is None or camera.latitude is None or camera.longitude is None:
        return InputMetadata(captured_at=item.captured_at)
    origin_by_pose = {
        "METADATA": LocationOrigin.METADATA,
        "USER_DECLARED": LocationOrigin.USER_DECLARED,
        "HUMAN_CONFIRMED": LocationOrigin.HUMAN_CONFIRMED,
    }
    origin = origin_by_pose.get(camera.pose_origin or "")
    if origin is None:
        # A cross-view estimate is not a camera capture location accepted by the v1 contract.
        # The v2 projection stage handles it explicitly and otherwise abstains.
        return InputMetadata(captured_at=item.captured_at)
    return InputMetadata(
        captured_at=item.captured_at,
        latitude=camera.latitude,
        longitude=camera.longitude,
        gps_accuracy_m=camera.horizontal_accuracy_m,
        location_origin=origin,
    )


def to_legacy_input(batch: WorkerInputV2) -> WorkerInput:
    """Reuse the audited sequential GPU stages without weakening either contract."""

    return WorkerInput.model_validate(
        {
            "schema_version": "1.0",
            "batch_id": batch.batch_id,
            "batch_type": batch.batch_type,
            "priority": batch.priority,
            "deadline_at": batch.deadline_at,
            "items": [
                {
                    "input_id": item.input_id,
                    "media_type": item.media_type,
                    "working_file_url": item.working_file_url,
                    "metadata": _legacy_metadata(item).model_dump(mode="json", exclude_none=True),
                    "frames": [frame.model_dump(mode="json") for frame in item.frames],
                    "audio_url": item.audio_url,
                    "article_text": item.article_text,
                    "source_context": item.provenance.model_dump(
                        mode="json",
                        include={
                            "source_reference_url",
                            "attribution",
                            "trust",
                            "source_kind",
                            "source_confidence",
                            "publication_policy",
                            "claim_types",
                            "declared_observation",
                        },
                        exclude_none=True,
                    ),
                }
                for item in batch.items
            ],
        }
    )


V2EvidenceKind = Literal["image", "frame", "satellite_image"]
SemanticAnchor = Literal["active_fire_point", "visible_fire_front_point", "smoke_column_base"]
FactCategory = Literal[
    "fire_activity",
    "burned_area",
    "resources",
    "evacuation",
    "access",
    "infrastructure",
    "weather",
    "other",
]


def _evidence_kind(item: WorkerBatchItemV2, evidence_id: str) -> V2EvidenceKind:
    if item.media_type.value == "satellite_image":
        return "satellite_image"
    if any(frame.frame_id == evidence_id for frame in item.frames):
        return "frame"
    return "image"


def _semantic_anchor(label: str) -> SemanticAnchor | None:
    lowered = label.casefold()
    if "smoke" in lowered or "fum" in lowered:
        return "smoke_column_base"
    if "flame" in lowered or "fire" in lowered or "feu" in lowered:
        return "active_fire_point"
    return None


def _source_annotations(
    item: WorkerBatchItemV2, legacy_result: ItemResult
) -> tuple[SourceAnnotationV2, ...]:
    regions = legacy_result.pixel_regions
    annotations: list[SourceAnnotationV2] = []
    for region in regions:
        anchor = _semantic_anchor(region.label)
        if anchor is None:
            continue
        x1, y1, x2, y2 = region.bbox_normalized
        annotations.append(
            SourceAnnotationV2(
                annotation_id=_stable_id("ANN", item.input_id, region.region_id, anchor),
                evidence_id=region.evidence_id,
                evidence_kind=_evidence_kind(item, region.evidence_id),
                semantic_anchor=anchor,
                source_point_normalized=((x1 + x2) / 2, (y1 + y2) / 2),
                model_score=region.model_score,
            )
        )
    return tuple(annotations)


def _satellite_ground_point(
    batch: WorkerInputV2,
    item: WorkerBatchItemV2,
    annotation: SourceAnnotationV2,
) -> SpatialProposalV2 | None:
    satellite = item.satellite
    reference = batch.reference_bundle
    if satellite is None or reference is None:
        return None
    normalized_crs = satellite.crs.upper().replace(" ", "")
    if normalized_crs not in {"EPSG:4326", "OGC:CRS84", "CRS84"}:
        return None
    x_normalized, y_normalized = annotation.source_point_normalized
    x_pixel = x_normalized * satellite.raster_width_px
    y_pixel = y_normalized * satellite.raster_height_px
    origin_x, pixel_x, rotation_x, origin_y, rotation_y, pixel_y = satellite.geotransform
    longitude = origin_x + x_pixel * pixel_x + y_pixel * rotation_x
    latitude = origin_y + x_pixel * rotation_y + y_pixel * pixel_y
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        return None
    return SpatialProposalV2(
        proposal_id=_stable_id("SP", annotation.annotation_id, "satellite"),
        annotation_id=annotation.annotation_id,
        status="ground_point",
        observed_at=satellite.acquired_at,
        geometry_origin="SATELLITE_GEOTRANSFORM",
        longitude=longitude,
        latitude=latitude,
        horizontal_accuracy_m=max(satellite.resolution_m * 2, 1.0),
        reference_bundle_sha256=reference.manifest_sha256,
    )


def _abstention_codes(batch: WorkerInputV2, item: WorkerBatchItemV2) -> tuple[str, ...]:
    if batch.reference_bundle is None:
        return ("reference_bundle_missing",)
    if item.media_type.value == "satellite_image":
        return ("satellite_crs_projection_unsupported",)
    if item.camera is None:
        return ("camera_pose_missing",)
    if item.camera.latitude is None or item.camera.longitude is None:
        return ("camera_position_missing",)
    if item.camera.yaw_deg is None:
        return ("camera_orientation_missing",)
    return ("terrain_raycast_unavailable",)


def _spatial_proposals(
    batch: WorkerInputV2,
    item: WorkerBatchItemV2,
    annotations: tuple[SourceAnnotationV2, ...],
) -> tuple[SpatialProposalV2, ...]:
    if not annotations and (item.working_file_url is not None or item.frames):
        return (
            SpatialProposalV2(
                proposal_id=_stable_id("SP", item.input_id, "no-anchor"),
                status="insufficient_geometry",
                uncertainty_codes=("active_fire_anchor_not_extracted",),
            ),
        )
    proposals: list[SpatialProposalV2] = []
    for annotation in annotations:
        projected = _satellite_ground_point(batch, item, annotation)
        proposals.append(
            projected
            or SpatialProposalV2(
                proposal_id=_stable_id("SP", annotation.annotation_id, "abstain"),
                annotation_id=annotation.annotation_id,
                status="insufficient_geometry",
                observed_at=item.captured_at,
                uncertainty_codes=_abstention_codes(batch, item),
            )
        )
    return tuple(proposals)


def _fact_category(fact_type: str) -> FactCategory:
    lowered = fact_type.casefold()
    if any(token in lowered for token in ("burned_area", "surface_brul", "hectare")):
        return "burned_area"
    if any(token in lowered for token in ("smoke", "flame", "fire", "fum", "feu", "progression")):
        return "fire_activity"
    if any(
        token in lowered
        for token in (
            "vehicle",
            "aircraft",
            "personnel",
            "pompier",
            "avion",
            "helicop",
            "resource",
            "moyen",
            "donation",
            "don_",
        )
    ):
        return "resources"
    if any(
        token in lowered for token in ("evac", "confin", "shelter", "hébergement", "hebergement")
    ):
        return "evacuation"
    if any(token in lowered for token in ("route", "road", "access", "restriction", "fermeture")):
        return "access"
    if any(
        token in lowered
        for token in (
            "building",
            "infrastructure",
            "bâtiment",
            "casualty",
            "damage",
            "victime",
            "degat",
            "service_disruption",
        )
    ):
        return "infrastructure"
    if any(
        token in lowered
        for token in (
            "weather",
            "wind",
            "vent",
            "météo",
            "air_quality",
            "pollution",
        )
    ):
        return "weather"
    return "other"


def _safe_fact_key(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._:-]+", "_", value).strip("_.:-")
    if not normalized:
        normalized = "observation"
    return normalized[:128]


def _fact_proposals(
    batch: WorkerInputV2,
    item: WorkerBatchItemV2,
    legacy_result: ItemResult,
) -> tuple[FactProposalV2, ...]:
    facts: list[FactProposalV2] = []
    for index, observation in enumerate(legacy_result.factual_observations, start=1):
        evidence_kind: Literal[
            "frame",
            "image",
            "satellite_image",
            "transcript_segment",
            "article_text",
            "metadata",
        ] = (
            "satellite_image"
            if observation.evidence_kind == "image" and item.media_type.value == "satellite_image"
            else observation.evidence_kind
        )
        facts.append(
            FactProposalV2(
                fact_id=_stable_id(
                    "FACT", item.input_id, str(index), observation.type, observation.description
                ),
                input_id=item.input_id,
                category=_fact_category(observation.type),
                fact_key=_safe_fact_key(observation.type),
                as_of=(
                    item.captured_at
                    or (item.satellite.acquired_at if item.satellite else None)
                    or batch.analysis_window.window_end_at
                ),
                evidence_kind=evidence_kind,
                evidence_id=observation.evidence_id,
                certainty=observation.certainty,
                value_text=observation.description,
                summary=observation.description,
            )
        )
    return tuple(facts)


def _report(batch: WorkerInputV2, items: tuple[WorkerItemResultV2, ...]) -> SituationReportDraftV2:
    section_for_category = {
        "fire_activity": "observed_activity",
        "burned_area": "observed_activity",
        "resources": "resources",
        "evacuation": "impacts",
        "access": "impacts",
        "infrastructure": "impacts",
        "weather": "situation",
        "other": "situation",
    }
    headings = {
        "situation": "Situation et consignes",
        "observed_activity": "Activité observée",
        "resources": "Moyens engagés",
        "impacts": "Population, impacts et accès",
    }
    source_by_input = {item.input_id: item.provenance for item in batch.items}

    def sourced_fact_line(fact: FactProposalV2) -> str:
        source = source_by_input[fact.input_id]
        label = source.attribution or source.source_policy_domain or source.source_key
        status = (
            "rapporté, à recouper"
            if source.source_confidence == "lead" or source.source_kind == "press"
            else "source institutionnelle ou technique"
        )
        return f"- {fact.summary} — {label}, {fact.as_of.isoformat()} ({status})"

    facts_by_section: dict[str, list[FactProposalV2]] = defaultdict(list)
    for result in items:
        for fact in result.fact_proposals:
            facts_by_section[section_for_category[fact.category]].append(fact)
    sections: list[ReportSectionV2] = []
    for key in ("situation", "observed_activity", "resources", "impacts"):
        facts = facts_by_section.get(key, [])
        if not facts:
            continue
        sections.append(
            ReportSectionV2(
                key=key,
                heading=headings[key],
                body="\n".join(sourced_fact_line(fact) for fact in facts),
                fact_ids=tuple(fact.fact_id for fact in facts),
            )
        )
    all_facts = [fact for result in items for fact in result.fact_proposals]
    if all_facts:
        sources: dict[str, tuple[str, str, str]] = {}
        for fact in all_facts:
            source = source_by_input[fact.input_id]
            url = str(source.source_reference_url) if source.source_reference_url else "sans URL"
            label = source.attribution or source.source_policy_domain or source.source_key
            confidence = source.source_confidence or source.trust
            sources[source.source_key] = (label, confidence, url)
        sections.append(
            ReportSectionV2(
                key="sources_and_freshness",
                heading="Sources et fraîcheur",
                body="\n".join(
                    f"- {label} — niveau {confidence} — {url}"
                    for label, confidence, url in sources.values()
                ),
                fact_ids=tuple(fact.fact_id for fact in all_facts),
            )
        )
    if not sections:
        codes = sorted(
            {
                code
                for result in items
                for proposal in result.spatial_proposals
                for code in proposal.uncertainty_codes
            }
        ) or ["no_explicit_fact_extracted"]
        sections.append(
            ReportSectionV2(
                key="limitations",
                heading="Limites",
                body="Aucun fait explicite exploitable n'a été extrait pour cette fenêtre.",
                basis_codes=tuple(codes),
            )
        )
    body = "\n\n".join(f"## {section.heading}\n\n{section.body}" for section in sections)
    return SituationReportDraftV2(
        title=f"Point de situation du {batch.analysis_window.local_date.isoformat()}",
        body_markdown=body,
        sections=tuple(sections),
    )


def from_legacy_output(
    batch: WorkerInputV2,
    legacy: WorkerOutput,
    *,
    stage_traces: tuple[WorkerStageTraceV2, ...],
    candidate_runs: tuple[WorkerModelCandidateRunV2, ...],
    consensus_results: tuple[WorkerConsensusResultV2, ...],
    contract_digest: str,
    spatial_pipeline: DeterministicSpatialPipeline | None = None,
) -> WorkerOutputV2:
    source_by_id = {item.input_id: item for item in batch.items}
    prepared: list[tuple[ItemResult, WorkerBatchItemV2, tuple[SourceAnnotationV2, ...]]] = []
    annotations_by_input: dict[str, tuple[SourceAnnotationV2, ...]] = {}
    for legacy_result in legacy.items:
        source = source_by_id[legacy_result.input_id]
        annotations = _source_annotations(source, legacy_result)
        prepared.append((legacy_result, source, annotations))
        annotations_by_input[source.input_id] = annotations
    spatial_execution = (
        spatial_pipeline.project(
            batch,
            annotations_by_input,
            sequence_start=len(stage_traces) + 1,
        )
        if spatial_pipeline is not None
        else None
    )
    items: list[WorkerItemResultV2] = []
    for legacy_result, source, annotations in prepared:
        spatial_proposals = (
            spatial_execution.proposals_by_input.get(source.input_id)
            if spatial_execution is not None
            else None
        )
        items.append(
            WorkerItemResultV2(
                input_id=source.input_id,
                transcript=legacy_result.transcript,
                pixel_regions=legacy_result.pixel_regions,
                visual_evidence_selection=legacy_result.visual_evidence_selection,
                source_annotations=annotations,
                spatial_proposals=(
                    spatial_proposals
                    if spatial_proposals is not None
                    else _spatial_proposals(batch, source, annotations)
                ),
                fact_proposals=_fact_proposals(batch, source, legacy_result),
                explicit_places=legacy_result.explicit_places,
                explicit_times=legacy_result.explicit_times,
                requires_human_review=True,
            )
        )
    runs = tuple(
        WorkerModelRunV2(
            model_role=(
                "visual_filtering" if run.model_role == "fire_detection" else run.model_role
            ),
            model_id=run.model_id,
            revision=run.revision,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            load_ms=run.load_ms,
            inference_ms=run.inference_ms,
            peak_vram_bytes=run.peak_vram_bytes,
            error_code=run.error_code,
        )
        for run in legacy.model_runs
    ) + (spatial_execution.model_runs if spatial_execution is not None else ())
    result_items = tuple(items)
    return WorkerOutputV2(
        batch_id=batch.batch_id,
        analysis_id=batch.analysis_window.analysis_id,
        status=legacy.status,
        retryable=legacy.retryable,
        orchestration_contract_digest=contract_digest,
        stage_traces=(
            stage_traces + spatial_execution.stage_traces
            if spatial_execution is not None
            else stage_traces
        ),
        model_runs=runs,
        candidate_runs=candidate_runs,
        consensus_results=consensus_results,
        items=result_items,
        report_draft=_report(batch, result_items),
        validation_errors=legacy.validation_errors,
        boot_ms=legacy.boot_ms,
    )
