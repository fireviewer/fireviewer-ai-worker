from __future__ import annotations

from firewarning_worker.mvp.contracts import EventEvidenceV1
from firewarning_worker.mvp.research.source_planner import (
    AutomaticSourceAcquisitionPlanner,
)
from firewarning_worker.mvp.supervision.backend_event_evidence import DurableEventEvidence


def _durable(*, label: str | None) -> DurableEventEvidence:
    event = EventEvidenceV1.model_validate(
        {
            "event_id": "EC-REAL-1",
            "time_window": {"from_at": "2026-08-23T12:00:00Z"},
        }
    )
    return DurableEventEvidence(
        event=event,
        media_locations=(),
        vision_artifacts=(),
        upload_locations=(),
        prior_fire_states=(),
        geospatial_checks=(),
        geographic_references=(),
        source_revision_sha256="a" * 64,
        viewpoint_label=label,
    )


def test_automatic_planner_builds_stable_queries_and_twenty_media_target() -> None:
    planner = AutomaticSourceAcquisitionPlanner()

    first = planner.build(_durable(label="Massif des Maures"))
    replay = planner.build(_durable(label="Massif des Maures"))

    assert first == replay
    assert first.plan_id.startswith("PLAN-AUTO-")
    assert first.target_media == 20
    assert len(first.source_policies) >= 20
    assert all("Massif des Maures" in query for query in first.queries)
    assert first.search_provider_domain not in first.allowed_domains


def test_automatic_planner_does_not_send_contact_data_or_coordinates_to_search() -> None:
    planner = AutomaticSourceAcquisitionPlanner()

    plan = planner.build(_durable(label="06 12 34 56 78 contact@example.org"))

    assert all("contact" not in query for query in plan.queries)
    assert all("example.org" not in query for query in plan.queries)
    assert all("06 12" not in query for query in plan.queries)
    assert plan.queries[0] == "incendie 2026-08-23"
