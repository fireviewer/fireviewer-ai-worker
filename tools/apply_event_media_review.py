from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze manual event-media review decisions as full SHA-256 selections."
    )
    parser.add_argument("inventory", type=Path)
    parser.add_argument("decisions", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    inventory_bytes = args.inventory.read_bytes()
    inventory = json.loads(inventory_bytes)
    decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
    if inventory.get("schema") != "fireviewer.event-media-inventory.v1":
        raise ValueError("unexpected event-media inventory schema")
    if decisions.get("schema") != "fireviewer.event-media-review-decisions.v1":
        raise ValueError("unexpected event-media review schema")
    minimum = int(decisions["minimum_media_per_case"])
    inventory_cases = {case["case_id"]: case for case in inventory["cases"]}
    decision_cases = {case["case_id"]: case for case in decisions["cases"]}
    if inventory_cases.keys() != decision_cases.keys():
        raise ValueError("review decisions must cover exactly the inventory cases")

    output_cases: list[dict[str, object]] = []
    for case_id, inventory_case in inventory_cases.items():
        indices = [int(index) for index in decision_cases[case_id]["accepted_indices"]]
        if len(indices) != len(set(indices)):
            raise ValueError(f"duplicate accepted index for {case_id}")
        if len(indices) < minimum:
            raise ValueError(f"reviewed media threshold not met for {case_id}")
        media = inventory_case["media"]
        if any(index < 1 or index > len(media) for index in indices):
            raise ValueError(f"accepted index is outside the inventory for {case_id}")
        selected = []
        for index in indices:
            item = dict(media[index - 1])
            item["inventory_index"] = index
            item["review_status"] = "accepted_visual_relevance"
            selected.append(item)
        digests = [item["sha256"] for item in selected]
        if len(digests) != len(set(digests)):
            raise ValueError(f"review selected duplicate media for {case_id}")
        output_cases.append(
            {
                "case_id": case_id,
                "selected_media_count": len(selected),
                "minimum_media_count": minimum,
                "media_threshold_met": len(selected) >= minimum,
                "candidate_media_count": inventory_case["unique_media_count"],
                "rejected_media_count": len(media) - len(selected),
                "contact_sheet_path": inventory_case["contact_sheet_path"],
                "media": selected,
            }
        )
    output = {
        "schema": "fireviewer.event-media-reviewed-selection.v1",
        "inventory_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
        "decisions_sha256": hashlib.sha256(args.decisions.read_bytes()).hexdigest(),
        "reviewed_at": decisions["reviewed_at"],
        "review_method": decisions["review_method"],
        "acceptance_rule": decisions["acceptance_rule"],
        "rejection_rule": decisions["rejection_rule"],
        "minimum_media_per_case": minimum,
        "media_gate": "pass",
        "rights_gate": "not_evaluated",
        "benchmark_quality_verdict": None,
        "cases": output_cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
