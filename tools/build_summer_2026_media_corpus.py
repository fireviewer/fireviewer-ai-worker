from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from firewarning_worker.mvp.benchmarks.corpus import Summer2026Corpus


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge the reviewed event-media selection into the summer 2026 corpus."
    )
    parser.add_argument("base_corpus", type=Path)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("reviewed_selection", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


def _origin_id(url: str) -> str:
    hostname = urlsplit(url).hostname or "unknown-source"
    normalized = re.sub(r"[^A-Za-z0-9._:-]+", "-", hostname.lower()).strip("-")
    return f"origin-{normalized}"[:128]


def _claim_summary(source: dict[str, object], case_label: str) -> str:
    value = source.get("description") or source.get("title")
    if value:
        return str(value)[:1_000]
    return f"Page source des médias examinés pour l'événement {case_label}."


def main() -> int:
    args = _arguments()
    corpus = json.loads(args.base_corpus.read_text(encoding="utf-8"))
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    reviewed = json.loads(args.reviewed_selection.read_text(encoding="utf-8"))
    if inventory.get("schema") != "fireviewer.event-media-inventory.v1":
        raise ValueError("unexpected event-media inventory schema")
    if reviewed.get("schema") != "fireviewer.event-media-reviewed-selection.v1":
        raise ValueError("unexpected reviewed event-media schema")
    if reviewed.get("media_gate") != "pass":
        raise ValueError("reviewed event-media gate must pass before corpus materialization")

    inventory_cases = {case["case_id"]: case for case in inventory["cases"]}
    reviewed_cases = {case["case_id"]: case for case in reviewed["cases"]}
    if {case["case_id"] for case in corpus["cases"]} != reviewed_cases.keys():
        raise ValueError("reviewed media must cover every corpus case")
    corpus["frozen_at"] = reviewed["reviewed_at"]

    for case in corpus["cases"]:
        case_id = case["case_id"]
        inventory_case = inventory_cases[case_id]
        reviewed_case = reviewed_cases[case_id]
        inventory_sources = {source["source_id"]: source for source in inventory_case["sources"]}
        sources_by_id = {source["source_id"]: source for source in case["sources"]}
        source_id_by_url = {str(source["url"]): source["source_id"] for source in case["sources"]}
        selected_source_ids = {item["source_id"] for item in reviewed_case["media"]}
        mapped_source_ids: dict[str, str] = {}
        for selected_source_id in selected_source_ids:
            source = inventory_sources[selected_source_id]
            source_url = str(source["final_url"])
            existing_id = source_id_by_url.get(source_url)
            if existing_id is not None:
                existing = sources_by_id[existing_id]
                existing["content_sha256"] = source["content_sha256"]
                existing["retrieved_at"] = inventory["generated_at"]
                mapped_source_ids[selected_source_id] = existing_id
                continue
            origin_id = _origin_id(source_url)
            added = {
                "source_id": selected_source_id,
                "origin_id": origin_id,
                "publisher": urlsplit(source_url).hostname or "Source média",
                "kind": "press",
                "url": source_url,
                "retrieved_at": inventory["generated_at"],
                "claim_summary": _claim_summary(source, case["label"]),
                "content_sha256": source["content_sha256"],
            }
            case["sources"].append(added)
            sources_by_id[selected_source_id] = added
            source_id_by_url[source_url] = selected_source_id
            mapped_source_ids[selected_source_id] = selected_source_id

        case["media"] = []
        for selected in reviewed_case["media"]:
            source_id = mapped_source_ids[selected["source_id"]]
            source = sources_by_id[source_id]
            case["media"].append(
                {
                    "media_id": selected["media_id"],
                    "origin_id": source["origin_id"],
                    "source_id": source_id,
                    "media_url": selected["media_url"],
                    "relative_path": selected["local_path"],
                    "media_sha256": selected["sha256"],
                    "rights_status": selected["rights_status"],
                }
            )

    validated = Summer2026Corpus.model_validate(corpus)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        validated.model_dump_json(by_alias=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
