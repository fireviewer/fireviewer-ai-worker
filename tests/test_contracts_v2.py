from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from firewarning_worker.contracts import (
    ReportSectionV2,
    SpatialProposalV2,
    WorkerInputV2,
    WorkerOutputV2,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "contracts" / "agent-worker" / "v2" / "examples"


def _example(name: str) -> dict[str, object]:
    value = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_worker_v2_accepts_the_shared_backend_examples() -> None:
    worker_input = WorkerInputV2.model_validate(_example("valid-input.json"))
    worker_output = WorkerOutputV2.model_validate(_example("valid-output.json"))

    assert worker_input.model_dump(mode="json")["schema_version"] == "2.0"
    assert worker_output.model_dump(mode="json")["analysis_id"] == "ANALYSIS-SYNTH-2026-07-09"
    assert worker_output.items[0].requires_human_review is True


def test_worker_v2_is_closed() -> None:
    payload = _example("valid-input.json")
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        WorkerInputV2.model_validate(payload)


def test_worker_v2_requires_complete_camera_orientation() -> None:
    payload = _example("valid-input.json")
    items = payload["items"]
    assert isinstance(items, list)
    assert isinstance(items[0], dict)
    camera = items[0]["camera"]
    assert isinstance(camera, dict)
    camera.pop("roll_deg")

    with pytest.raises(ValidationError, match="yaw, pitch, and roll"):
        WorkerInputV2.model_validate(payload)


def test_worker_v2_abstention_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="requires an uncertainty code"):
        SpatialProposalV2.model_validate(
            {
                "proposal_id": "SP-ABSTAIN",
                "annotation_id": "ANN-1",
                "status": "insufficient_geometry",
            }
        )


def test_worker_v2_abstention_does_not_require_a_source_annotation() -> None:
    proposal = SpatialProposalV2.model_validate(
        {
            "proposal_id": "SP-NO-ANCHOR",
            "status": "insufficient_geometry",
            "uncertainty_codes": ["anchor_not_visible"],
        }
    )

    assert proposal.annotation_id is None


def test_worker_v2_limitations_can_use_an_explicit_abstention_basis() -> None:
    section = ReportSectionV2.model_validate(
        {
            "key": "limitations",
            "heading": "Limites",
            "body": "La pose caméra ne permet pas une projection fiable.",
            "basis_codes": ["camera_pose_missing"],
        }
    )

    assert section.fact_ids == ()


def test_worker_v2_report_references_are_closed() -> None:
    payload = _example("valid-output.json")
    report = payload["report_draft"]
    assert isinstance(report, dict)
    sections = report["sections"]
    assert isinstance(sections, list)
    assert isinstance(sections[0], dict)
    sections[0]["fact_ids"] = ["FACT-NOT-PRESENT"]

    with pytest.raises(ValidationError, match="unknown fact"):
        WorkerOutputV2.model_validate(payload)


def test_worker_v2_stage_trace_sequences_cannot_overlap() -> None:
    payload = _example("valid-output.json")
    traces = payload["stage_traces"]
    assert isinstance(traces, list)
    duplicate = deepcopy(traces[0])
    assert isinstance(duplicate, dict)
    duplicate["stage_role"] = "asr"
    duplicate["contract_id"] = "stage.asr.v1"
    traces.append(duplicate)

    with pytest.raises(ValidationError, match="duplicate stage sequences"):
        WorkerOutputV2.model_validate(payload)
