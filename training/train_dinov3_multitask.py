"""Fail-closed preparation gate for full DINOv3 FireViewer fine-tuning.

The revised challenger contract requires segmentation masks, anchor heatmaps,
and explicit visual-abstention labels.  The current ground-point corpus is
kept as an input audit, but it is not silently promoted to a segmentation
dataset.  A future canonical manifest can use the shared challenger schema
and then be passed to the real full-fine-tuning entrypoint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from training.challenger_training import ALL_SPLITS, APPROVED_SAMPLE_STATUSES

DEFAULT_POINTING_ROOT = Path(
    os.environ.get(
        "FIREVIEWER_POINTING_DATASET_ROOT",
        "data/datasets/fire-smoke-pointing-ground-v1",
    )
)
DEFAULT_OUTPUT = Path("data/training/dinov3-multitask-v1")
DEFAULT_MODEL = "facebook/dinov3-vitb16-pretrain-lvd1689m"
DEFAULT_MODEL_REVISION = "5931719e67bbdb9737e363e781fb0c67687896bc"
DEFAULT_MULTITASK_MANIFEST = Path("data/training/dinov3-boreal-multitask-v1/manifest.jsonl")
DEFAULT_DATA_ROOT = Path(
    "data/training/wildfire-smoke-segmentation-v1/"
    "wildfire-smoke-segmentation-v1/sources/boreal-forest-fire-segmentation-v1"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_pointing_manifest(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    path = root / "manifest.jsonl"
    if not path.is_file():
        return [], [f"missing:{path}"]
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid_json:{line_number}:{exc.msg}")
            continue
        if not isinstance(row, dict):
            errors.append(f"row_not_object:{line_number}")
            continue
        rows.append(row)
    return rows, errors


def build_preflight_report(
    *,
    pointing_root: Path,
    multitask_manifest: Path | None,
    model_id: str,
    model_revision: str,
) -> dict[str, Any]:
    pointing_root = pointing_root.resolve()
    rows, errors = _read_pointing_manifest(pointing_root)
    warnings: list[str] = []
    split_counts = Counter(str(row.get("split")) for row in rows)
    target_counts = Counter(
        str(target.get("semantic_anchor"))
        for row in rows
        for target in row.get("targets", [])
        if isinstance(target, dict)
    )
    empty_target_rows = sum(not row.get("targets") for row in rows)
    if rows and set(split_counts) != ALL_SPLITS:
        errors.append(f"missing_split:{sorted(ALL_SPLITS - set(split_counts))}")
    if rows and empty_target_rows:
        warnings.append(f"pointing_abstention_rows:{empty_target_rows}")
    if rows and not (pointing_root / "report.json").is_file():
        errors.append("pointing_report_missing")
    if rows and not (pointing_root / "checksums.sha256").is_file():
        errors.append("pointing_checksums_missing")

    mask_manifest_ready = False
    mask_quality_counts: Counter[str] = Counter()
    if multitask_manifest is None:
        errors.append("multitask_manifest_required_for_segmentation")
    else:
        path = multitask_manifest.resolve()
        if not path.is_file():
            errors.append(f"missing:{path}")
        else:
            mask_manifest_ready = True
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"multitask_manifest_invalid_json:{line_number}:{exc.msg}")
                    continue
                if not isinstance(row, dict):
                    errors.append(f"multitask_manifest_row_not_object:{line_number}")
                    continue
                if not row.get("mask_relpath") or not row.get("mask_sha256"):
                    errors.append(f"mask_missing:{line_number}")
                if not isinstance(row.get("anchor_points"), list):
                    errors.append(f"anchor_points_missing:{line_number}")
                if "visual_abstention_reason" not in row:
                    errors.append(f"visual_abstention_label_missing:{line_number}")
                if not row.get("mask_quality"):
                    errors.append(f"mask_quality_missing:{line_number}")
                else:
                    mask_quality_counts[str(row["mask_quality"])] += 1
                if row.get("sample_validation_status") not in APPROVED_SAMPLE_STATUSES:
                    errors.append(f"sample_not_validated:{line_number}")

    if not model_revision.strip() or model_revision.startswith("<"):
        errors.append("model_revision_required")

    return {
        "schema_version": 1,
        "model_family": "DINOv3 multi-task",
        "model_id": model_id,
        "model_revision": model_revision,
        "fine_tuning_mode": "full_model_all_parameters_trainable",
        "pointing_corpus": {
            "root": str(pointing_root),
            "manifest_sha256": (
                _sha256(pointing_root / "manifest.jsonl")
                if (pointing_root / "manifest.jsonl").is_file()
                else None
            ),
            "rows": len(rows),
            "split_counts": dict(sorted(split_counts.items())),
            "target_counts": dict(sorted(target_counts.items())),
            "empty_target_rows": empty_target_rows,
        },
        "multitask_manifest": str(multitask_manifest.resolve()) if multitask_manifest else None,
        "training_errors": errors,
        "training_warnings": warnings,
        "training_ready": not errors,
        "promotion_ready": False,
        "promotion_errors": ["shadow_benchmark_missing", "human_review_required"],
        "mask_manifest_detected": mask_manifest_ready,
        "mask_quality_counts": dict(sorted(mask_quality_counts.items())),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FireViewer DINOv3 multi-task training gate")
    parser.add_argument("command", choices=("preflight", "plan", "train"))
    parser.add_argument("--pointing-root", type=Path, default=DEFAULT_POINTING_ROOT)
    parser.add_argument("--multitask-manifest", type=Path, default=DEFAULT_MULTITASK_MANIFEST)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--model-id", default=DEFAULT_MODEL)
    parser.add_argument("--model-revision", default=DEFAULT_MODEL_REVISION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.epochs <= 0 or args.batch_size <= 0 or args.gradient_accumulation_steps <= 0:
        raise ValueError("epochs, batch-size and gradient-accumulation-steps must be positive")
    report = build_preflight_report(
        pointing_root=args.pointing_root,
        multitask_manifest=args.multitask_manifest,
        model_id=args.model_id,
        model_revision=args.model_revision,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    _write_json(args.output / "preflight-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.command == "preflight":
        if not report["training_ready"]:
            raise SystemExit(2)
        return
    plan = {
        "schema_version": 1,
        "model_family": report["model_family"],
        "model_id": args.model_id,
        "model_revision": args.model_revision,
        "data_root": str(args.data_root.resolve()),
        "adapter": "training.dinov3_adapter:DinoV3MultiTaskModel",
        "fine_tuning_mode": report["fine_tuning_mode"],
        "hyperparameters": {
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "gradient_accumulation_steps": args.gradient_accumulation_steps,
            "learning_rate": args.learning_rate,
            "seed": args.seed,
        },
        "gates": ["masks", "anchor_heatmaps", "visual_abstention", "split_group_isolation"],
        "training_ready": report["training_ready"],
    }
    _write_json(args.output / "training-plan.json", plan)
    if args.command == "plan":
        return
    if not report["training_ready"]:
        raise RuntimeError("DINOv3 training gate failed; provide the canonical multi-task manifest")
    from training.dinov3_adapter import run_training

    try:
        result = run_training(
            manifest=args.multitask_manifest.resolve(),
            data_root=args.data_root.resolve(),
            output=args.output.resolve(),
            model_id=args.model_id,
            model_revision=args.model_revision,
            epochs=args.epochs,
            batch_size=args.batch_size,
            gradient_accumulation_steps=args.gradient_accumulation_steps,
            learning_rate=args.learning_rate,
            seed=args.seed,
            image_size=224,
            num_workers=0,
        )
    except OSError as exc:
        raise RuntimeError(
            "DINOv3 backbone is not locally available; accept the gated model "
            "terms and grant the HF token public-gated read access before train"
        ) from exc
    _write_json(args.output / "training-result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
