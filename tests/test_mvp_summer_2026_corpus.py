from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from firewarning_worker.mvp.benchmarks.corpus import Summer2026Corpus
from firewarning_worker.mvp.benchmarks.ground_truth import (
    GroundTruthParseError,
    summarize_observed_event_geojson,
)

CORPUS_PATH = (
    Path(__file__).parents[1]
    / "benchmarks"
    / "mvp-event-localization"
    / "corpus"
    / "france-summer-2026-candidates.v1.json"
)
PREFLIGHT_PATH = CORPUS_PATH.with_name("france-summer-2026-preflight-20260821.json")
MEDIA_CORPUS_PATH = CORPUS_PATH.with_name("france-summer-2026-media-ready.v1.json")
MEDIA_SELECTION_PATH = CORPUS_PATH.with_name("event-media-reviewed-selection-20260821.json")


def test_summer_2026_candidate_corpus_keeps_die_and_reports_real_blockers() -> None:
    corpus = Summer2026Corpus.model_validate_json(CORPUS_PATH.read_text(encoding="utf-8"))

    assert len(corpus.cases) == 9
    assert corpus.cases[0].case_id == "FR-2026-06-DIE-JUSTIN"
    assert corpus.cases[0].event_date.isoformat() == "2026-06-24"
    assert {case.event_date.month for case in corpus.cases} == {6, 7, 8}
    assert len(corpus.canonical_sha256()) == 64
    assert sum(case.ground_truth.status == "available" for case in corpus.cases) == 5

    readiness = corpus.readiness_report()
    assert readiness.ready_case_count == 0
    die = next(item for item in readiness.cases if item.case_id == "FR-2026-06-DIE-JUSTIN")
    assert "ground_truth_not_available" not in die.blocker_codes
    assert "event_media_below_minimum" in die.blocker_codes
    assert "source_snapshot_missing" in die.blocker_codes


def test_real_preflight_receipt_matches_the_frozen_corpus_without_quality_verdict() -> None:
    corpus = Summer2026Corpus.model_validate_json(CORPUS_PATH.read_text(encoding="utf-8"))
    receipt = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))

    assert receipt["corpus_sha256"] == corpus.canonical_sha256()
    assert receipt["quality_verdict"] is None
    assert receipt["panoramax"]["downloaded_media_count"] == 0
    assert len(receipt["panoramax"]["cases"]) == 9

    truths = {item["case_id"]: item for item in receipt["ground_truth"]}
    assert truths["FR-2026-06-DIE-JUSTIN"]["status"] == "available"
    assert truths["FR-2026-06-DIE-JUSTIN"]["declared_summary_matches"] is True
    assert truths["FR-2026-06-DIE-JUSTIN"]["summary"]["feature_count"] == 151

    coverage = {item["case_id"]: item for item in receipt["panoramax"]["cases"]}
    assert coverage["FR-2026-06-DIE-JUSTIN"]["reference_count"] == 25
    assert coverage["FR-2026-08-LUGLON"]["reference_count"] == 0


def test_reviewed_media_corpus_has_twenty_verified_digests_per_case() -> None:
    corpus = Summer2026Corpus.model_validate_json(MEDIA_CORPUS_PATH.read_text(encoding="utf-8"))
    selection = json.loads(MEDIA_SELECTION_PATH.read_text(encoding="utf-8"))

    assert selection["media_gate"] == "pass"
    assert selection["rights_gate"] == "not_evaluated"
    assert selection["benchmark_quality_verdict"] is None
    assert len(corpus.cases) == 9
    assert sum(len(case.media) for case in corpus.cases) == 180
    assert all(len(case.media) == 20 for case in corpus.cases)
    assert all(len({item.media_sha256 for item in case.media}) == 20 for case in corpus.cases)
    assert all(
        item.relative_path is not None and item.media_sha256 is not None
        for case in corpus.cases
        for item in case.media
    )
    assert all(
        item.rights_status == "not_checked_internal_benchmark"
        for case in corpus.cases
        for item in case.media
    )
    for readiness in corpus.readiness_report().cases:
        assert "event_media_below_minimum" not in readiness.blocker_codes
        assert "media_digest_missing" not in readiness.blocker_codes
        assert "media_license_missing" not in readiness.blocker_codes


def test_observed_event_summary_is_byte_exact_and_derives_bounded_truth() -> None:
    payload = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"area": 12.5},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[5.3, 44.7], [5.4, 44.7], [5.4, 44.8], [5.3, 44.8], [5.3, 44.7]]
                        ],
                    },
                }
            ],
        },
        separators=(",", ":"),
    ).encode()

    truth = summarize_observed_event_geojson(
        payload,
        source_url="https://example.test/observed-event.json",
        retrieved_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
    )

    assert truth.feature_count == 1
    assert truth.payload_size_bytes == len(payload)
    assert truth.bbox_wgs84 == pytest.approx((5.3, 44.7, 5.4, 44.8))
    assert truth.center_wgs84 == pytest.approx((5.35, 44.75))
    assert truth.radius_m > 0
    assert truth.source_area_sum == 12.5


def test_observed_event_summary_rejects_points() -> None:
    payload = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "Point", "coordinates": [5.3, 44.7]},
                }
            ],
        }
    ).encode()

    with pytest.raises(GroundTruthParseError, match="Polygon"):
        summarize_observed_event_geojson(
            payload,
            source_url="https://example.test/point.json",
            retrieved_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
        )
