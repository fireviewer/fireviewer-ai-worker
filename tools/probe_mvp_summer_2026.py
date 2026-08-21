from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from firewarning_worker.mvp.benchmarks.corpus import Summer2026Corpus
from firewarning_worker.mvp.benchmarks.coverage import probe_panoramax_coverage
from firewarning_worker.mvp.benchmarks.ground_truth import (
    MAX_GROUND_TRUTH_BYTES,
    GroundTruthParseError,
    summarize_observed_event_geojson,
)
from firewarning_worker.mvp.localization.panoramax import PanoramaxClient

ALLOWED_GROUND_TRUTH_HOST = "rapidmapping-viewer.s3.eu-west-1.amazonaws.com"


def _download_ground_truth(client: httpx.Client, url: str) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_GROUND_TRUTH_HOST:
        raise ValueError("ground-truth URL is outside the allowed Copernicus object host")
    payload = bytearray()
    with client.stream(
        "GET", url, headers={"Accept": "application/geo+json,application/json"}
    ) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            payload.extend(chunk)
            if len(payload) > MAX_GROUND_TRUTH_BYTES:
                raise ValueError("ground-truth payload exceeds the 64 MiB safety cap")
    return bytes(payload)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe Summer 2026 ground truth and Panoramax metadata without media downloads."
    )
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--panoramax-api", default="https://panoramax.ign.fr/api")
    parser.add_argument("--limit-per-case", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    corpus = Summer2026Corpus.model_validate_json(args.corpus.read_text(encoding="utf-8"))
    retrieved_at = datetime.now(UTC)
    ground_truth_results: list[dict[str, Any]] = []
    failures = 0
    with httpx.Client(timeout=90, follow_redirects=False) as client:
        for case in corpus.cases:
            ground_truth = case.ground_truth
            if ground_truth.status == "not_identified" or ground_truth.source_url is None:
                ground_truth_results.append(
                    {
                        "case_id": case.case_id,
                        "status": "not_probed",
                        "reason": ground_truth.status,
                    }
                )
                continue
            try:
                source_url = str(ground_truth.source_url)
                payload = _download_ground_truth(client, source_url)
                summary = summarize_observed_event_geojson(
                    payload,
                    source_url=source_url,
                    retrieved_at=retrieved_at,
                )
            except (GroundTruthParseError, ValueError, httpx.HTTPError) as exc:
                failures += 1
                ground_truth_results.append(
                    {
                        "case_id": case.case_id,
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:500],
                    }
                )
            else:
                declared_summary_matches = None
                if ground_truth.status == "available":
                    declared_summary_matches = (
                        ground_truth.content_sha256 == summary.content_sha256
                        and ground_truth.feature_count == summary.feature_count
                        and ground_truth.bbox_wgs84 == summary.bbox_wgs84
                        and ground_truth.center_wgs84 == summary.center_wgs84
                        and ground_truth.radius_m == summary.radius_m
                    )
                    if not declared_summary_matches:
                        failures += 1
                ground_truth_results.append(
                    {
                        "case_id": case.case_id,
                        "status": (
                            "available" if declared_summary_matches is not False else "mismatch"
                        ),
                        "declared_summary_matches": declared_summary_matches,
                        "summary": summary.model_dump(mode="json"),
                    }
                )

    coverage = probe_panoramax_coverage(
        corpus,
        client=PanoramaxClient(api_url=args.panoramax_api),
        retrieved_at=retrieved_at,
        limit_per_case=args.limit_per_case,
    )
    receipt = {
        "schema": "fireviewer.mvp-summer-2026-preflight.v1",
        "retrieved_at": retrieved_at.isoformat(),
        "corpus_sha256": corpus.canonical_sha256(),
        "ground_truth": ground_truth_results,
        "panoramax": coverage.model_dump(mode="json", by_alias=True),
        "quality_verdict": None,
        "quality_verdict_reason": "No event media were downloaded or localized during preflight.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
