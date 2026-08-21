from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

MINIMUM_MEDIA_PER_CASE = 20
CONTACT_SHEET_COLUMNS = 5
CONTACT_SHEET_CELL = (260, 190)
CONTACT_SHEET_HEADER_HEIGHT = 56


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify, deduplicate and render collected event-media candidates."
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("contact_sheet_root", type=Path)
    parser.add_argument(
        "--input",
        action="append",
        nargs=2,
        required=True,
        metavar=("RECEIPT", "COLLECTION_ROOT"),
    )
    return parser.parse_args()


def _contained_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError(f"media path leaves its collection root: {relative_path}")
    return candidate


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"artifact is outside the repository: {path}") from exc


def _verified_media(
    raw_media: dict[str, object],
    *,
    collection_root: Path,
    repo_root: Path,
    receipt_path: Path,
) -> dict[str, object]:
    relative_path = str(raw_media["relative_path"])
    media_path = _contained_path(collection_root, relative_path)
    content = media_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != raw_media["sha256"]:
        raise ValueError(f"media digest mismatch: {media_path}")
    if len(content) != raw_media["size_bytes"]:
        raise ValueError(f"media size mismatch: {media_path}")
    with Image.open(media_path) as image:
        image.load()
        dimensions = image.size
    if dimensions != (raw_media["width"], raw_media["height"]):
        raise ValueError(f"media dimensions mismatch: {media_path}")
    return {
        "media_id": raw_media["media_id"],
        "sha256": digest,
        "size_bytes": len(content),
        "content_type": raw_media["content_type"],
        "width": dimensions[0],
        "height": dimensions[1],
        "media_url": raw_media["media_url"],
        "source_id": raw_media["source_id"],
        "source_page_url": raw_media["source_page_url"],
        "local_path": _repo_relative(media_path, repo_root),
        "review_status": "not_reviewed",
        "rights_status": raw_media["rights_status"],
        "provenance": [
            {
                "receipt": _repo_relative(receipt_path, repo_root),
                "source_id": raw_media["source_id"],
                "source_page_url": raw_media["source_page_url"],
                "media_url": raw_media["media_url"],
            }
        ],
    }


def _merge_duplicate(existing: dict[str, object], candidate: dict[str, object]) -> None:
    provenance = existing["provenance"]
    assert isinstance(provenance, list)
    for item in candidate["provenance"]:
        if item not in provenance:
            provenance.append(item)


def _render_contact_sheet(
    case_id: str,
    media: list[dict[str, object]],
    *,
    output_root: Path,
) -> Path:
    columns = CONTACT_SHEET_COLUMNS
    rows = math.ceil(len(media) / columns)
    cell_width, cell_height = CONTACT_SHEET_CELL
    sheet = Image.new(
        "RGB",
        (columns * cell_width, CONTACT_SHEET_HEADER_HEIGHT + rows * cell_height),
        "#111827",
    )
    draw = ImageDraw.Draw(sheet)
    draw.text(
        (16, 16),
        f"{case_id} - {len(media)} medias uniques - controle requis",
        fill="white",
    )
    for index, item in enumerate(media):
        column = index % columns
        row = index // columns
        x = column * cell_width
        y = CONTACT_SHEET_HEADER_HEIGHT + row * cell_height
        with Image.open(str(item["_absolute_path"])) as source:
            rendered = ImageOps.contain(source.convert("RGB"), (cell_width - 12, cell_height - 34))
        image_x = x + (cell_width - rendered.width) // 2
        image_y = y + 4 + (cell_height - 34 - rendered.height) // 2
        sheet.paste(rendered, (image_x, image_y))
        draw.rectangle(
            (x + 2, y + 2, x + cell_width - 3, y + cell_height - 3),
            outline="#4b5563",
            width=1,
        )
        draw.text(
            (x + 7, y + cell_height - 25),
            f"{index + 1:02d} {str(item['sha256'])[:10]}",
            fill="#f9fafb",
        )
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / f"{case_id}.jpg"
    sheet.save(target, "JPEG", quality=90, optimize=True)
    return target.resolve()


def main() -> int:
    args = _arguments()
    repo_root = Path.cwd().resolve()
    cases: dict[str, dict[str, object]] = {}
    receipt_summaries: list[dict[str, object]] = []
    for receipt_argument, root_argument in args.input:
        receipt_path = Path(receipt_argument).resolve()
        collection_root = Path(root_argument).resolve()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("schema") != "fireviewer.event-media-research-receipt.v1":
            raise ValueError(f"unexpected receipt schema: {receipt_path}")
        receipt_summaries.append(
            {
                "path": _repo_relative(receipt_path, repo_root),
                "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            }
        )
        for raw_case in receipt["cases"]:
            case_id = str(raw_case["case_id"])
            case = cases.setdefault(
                case_id,
                {"sources": {}, "media_by_sha256": {}, "errors": []},
            )
            sources = case["sources"]
            media_by_sha256 = case["media_by_sha256"]
            errors = case["errors"]
            assert isinstance(sources, dict)
            assert isinstance(media_by_sha256, dict)
            assert isinstance(errors, list)
            for source in raw_case["sources"]:
                sources.setdefault(source["source_id"], source)
            errors.extend(raw_case["errors"])
            for raw_media in raw_case["media"]:
                candidate = _verified_media(
                    raw_media,
                    collection_root=collection_root,
                    repo_root=repo_root,
                    receipt_path=receipt_path,
                )
                candidate["_absolute_path"] = str(
                    _contained_path(collection_root, str(raw_media["relative_path"]))
                )
                digest = str(candidate["sha256"])
                existing = media_by_sha256.get(digest)
                if existing is None:
                    media_by_sha256[digest] = candidate
                else:
                    _merge_duplicate(existing, candidate)

    contact_sheet_root = args.contact_sheet_root.resolve()
    output_cases: list[dict[str, object]] = []
    for case_id, raw_case in cases.items():
        media = list(raw_case["media_by_sha256"].values())
        contact_sheet = _render_contact_sheet(
            case_id,
            media,
            output_root=contact_sheet_root,
        )
        for item in media:
            item.pop("_absolute_path")
        output_cases.append(
            {
                "case_id": case_id,
                "source_count": len(raw_case["sources"]),
                "unique_media_count": len(media),
                "minimum_media_count": MINIMUM_MEDIA_PER_CASE,
                "target_met": len(media) >= MINIMUM_MEDIA_PER_CASE,
                "reviewed_media_count": 0,
                "contact_sheet_path": _repo_relative(contact_sheet, repo_root),
                "sources": list(raw_case["sources"].values()),
                "media": media,
                "collection_error_count": len(raw_case["errors"]),
            }
        )
    output = {
        "schema": "fireviewer.event-media-inventory.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "minimum_media_per_case": MINIMUM_MEDIA_PER_CASE,
        "quality_verdict": None,
        "receipts": receipt_summaries,
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
