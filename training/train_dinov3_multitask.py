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
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any

from training.challenger_training import ALL_SPLITS, APPROVED_SAMPLE_STATUSES

TRAINABLE_SAMPLE_STATUSES = APPROVED_SAMPLE_STATUSES | frozenset(
    {"sensor_derived", "sensor_generated_weak", "teacher_generated_weak"}
)

DEFAULT_POINTING_ROOT = Path(
    os.environ.get(
        "FIREVIEWER_POINTING_DATASET_ROOT",
        "data/datasets/pointing-rebuild-required",
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
    data_root: Path,
    model_id: str,
    model_revision: str,
    initial_safetensors: Path | None = None,
    backbone_config: Path | None = None,
) -> dict[str, Any]:
    pointing_root = pointing_root.resolve()
    data_root = data_root.resolve()
    multitask_path = multitask_manifest.resolve() if multitask_manifest else None
    integrated_pointing = (
        multitask_path is not None
        and (pointing_root / "manifest.jsonl").resolve() == multitask_path
    )
    if (pointing_root / "manifest.jsonl").is_file() and not integrated_pointing:
        rows, errors = _read_pointing_manifest(pointing_root)
    else:
        rows, errors = [], []
    warnings: list[str] = []
    if not rows and not integrated_pointing:
        warnings.append("separate_pointing_corpus_absent_using_multitask_manifest")
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
    multitask_split_counts: Counter[str] = Counter()
    multitask_target_counts: Counter[str] = Counter()
    multitask_abstention_rows = 0
    sample_validation_status_counts: Counter[str] = Counter()
    invalid_sample_status_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    sample_weight_counts: Counter[str] = Counter()
    split_groups: dict[str, set[str]] = {}
    verified_artifacts = 0
    if multitask_manifest is None:
        errors.append("multitask_manifest_required_for_segmentation")
    else:
        path = multitask_path
        assert path is not None
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
                split = str(row.get("split"))
                multitask_split_counts[split] += 1
                source_counts[str(row.get("source_id") or "unknown")] += 1
                group = str(row.get("split_group"))
                split_groups.setdefault(group, set()).add(split)
                if not row.get("mask_relpath") or not row.get("mask_sha256"):
                    errors.append(f"mask_missing:{line_number}")
                points = row.get("anchor_points")
                if not isinstance(points, list):
                    errors.append(f"anchor_points_missing:{line_number}")
                    points = []
                for point in points:
                    if not isinstance(point, dict):
                        errors.append(f"anchor_point_invalid:{line_number}")
                        continue
                    kind = str(point.get("kind"))
                    multitask_target_counts[kind] += 1
                    try:
                        x, y = float(point["x"]), float(point["y"])
                    except (KeyError, TypeError, ValueError):
                        errors.append(f"anchor_point_invalid:{line_number}")
                        continue
                    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                        errors.append(f"anchor_point_out_of_bounds:{line_number}")
                if "visual_abstention_reason" not in row:
                    errors.append(f"visual_abstention_label_missing:{line_number}")
                elif row.get("visual_abstention_reason") is not None:
                    multitask_abstention_rows += 1
                    role_counts["abstention"] += 1
                elif str(row.get("annotation_strength")) in {
                    "negative",
                    "temporal_negative",
                }:
                    role_counts["negative"] += 1
                else:
                    role_counts["positive"] += 1
                try:
                    sample_weight = float(row.get("sample_weight", 1.0))
                except (TypeError, ValueError):
                    sample_weight = math.nan
                if not math.isfinite(sample_weight) or sample_weight <= 0.0:
                    errors.append(f"sample_weight_invalid:{line_number}")
                else:
                    sample_weight_counts[str(sample_weight)] += 1
                if not row.get("mask_quality"):
                    errors.append(f"mask_quality_missing:{line_number}")
                else:
                    mask_quality_counts[str(row["mask_quality"])] += 1
                sample_status = str(row.get("sample_validation_status"))
                sample_validation_status_counts[sample_status] += 1
                if sample_status not in TRAINABLE_SAMPLE_STATUSES:
                    invalid_sample_status_counts[sample_status] += 1
                artifacts = [
                    ("image_relpath", "image_sha256"),
                    ("mask_relpath", "mask_sha256"),
                ]
                if row.get("valid_mask_relpath") or row.get("valid_mask_sha256"):
                    artifacts.append(("valid_mask_relpath", "valid_mask_sha256"))
                for rel_key, sha_key in artifacts:
                    relpath, expected_sha = row.get(rel_key), row.get(sha_key)
                    if not relpath or not expected_sha:
                        errors.append(f"artifact_contract_missing:{line_number}:{rel_key}")
                        continue
                    artifact = (data_root / str(relpath)).resolve()
                    if artifact != data_root and data_root not in artifact.parents:
                        errors.append(f"artifact_path_escape:{line_number}:{rel_key}")
                    elif not artifact.is_file():
                        errors.append(f"artifact_missing:{line_number}:{rel_key}")
                    elif _sha256(artifact) != str(expected_sha).lower():
                        errors.append(f"artifact_checksum_mismatch:{line_number}:{rel_key}")
                    else:
                        verified_artifacts += 1

    if mask_manifest_ready and set(multitask_split_counts) != ALL_SPLITS:
        errors.append(f"multitask_missing_split:{sorted(ALL_SPLITS - set(multitask_split_counts))}")
    if invalid_sample_status_counts:
        errors.append(
            "sample_status_not_trainable:"
            + json.dumps(dict(sorted(invalid_sample_status_counts.items())), sort_keys=True)
        )
    leaking_groups = sorted(group for group, owners in split_groups.items() if len(owners) != 1)
    if leaking_groups:
        errors.append(f"multitask_split_group_leakage:{leaking_groups}")

    if not model_revision.strip() or model_revision.startswith("<"):
        errors.append("model_revision_required")
    if initial_safetensors is not None and not initial_safetensors.is_file():
        errors.append(f"initial_safetensors_missing:{initial_safetensors}")
    if initial_safetensors is not None and (
        backbone_config is None or not backbone_config.is_file()
    ):
        errors.append("backbone_config_required_with_initial_safetensors")

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
            "integrated_in_multitask_manifest": integrated_pointing,
        },
        "multitask_manifest": str(multitask_manifest.resolve()) if multitask_manifest else None,
        "multitask_manifest_sha256": _sha256(multitask_path)
        if multitask_path and multitask_path.is_file()
        else None,
        "multitask_split_counts": dict(sorted(multitask_split_counts.items())),
        "multitask_target_counts": dict(sorted(multitask_target_counts.items())),
        "multitask_abstention_rows": multitask_abstention_rows,
        "multitask_role_counts": dict(sorted(role_counts.items())),
        "multitask_source_counts": dict(sorted(source_counts.items())),
        "sample_weight_counts": dict(sorted(sample_weight_counts.items())),
        "verified_artifacts": verified_artifacts,
        "split_group_leakage": leaking_groups,
        "training_errors": errors,
        "training_warnings": warnings,
        "training_ready": not errors,
        "promotion_ready": False,
        "promotion_errors": ["shadow_benchmark_missing", "human_review_required"],
        "mask_manifest_detected": mask_manifest_ready,
        "mask_quality_counts": dict(sorted(mask_quality_counts.items())),
        "initialization": (
            "complete_v3_safetensors"
            if initial_safetensors is not None
            else "immutable_base_pretrained"
        ),
        "initial_safetensors": initial_safetensors.name if initial_safetensors else None,
        "backbone_config": backbone_config.name if backbone_config else None,
        "sample_validation_status_counts": dict(sorted(sample_validation_status_counts.items())),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FireViewer DINOv3 multi-task training gate")
    parser.add_argument("command", choices=("preflight", "plan", "smoke", "train"))
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
    parser.add_argument("--num-workers", type=int, default=8)
    parser.add_argument("--image-size", type=int, default=448)
    parser.add_argument("--early-stopping-patience", type=int, default=8)
    parser.add_argument("--initial-safetensors", type=Path)
    parser.add_argument("--backbone-config", type=Path)
    parser.add_argument(
        "--balanced-sampling",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--positive-share", type=float, default=0.48)
    parser.add_argument("--negative-share", type=float, default=0.28)
    parser.add_argument("--abstention-share", type=float, default=0.24)
    parser.add_argument("--pyro-max-share", type=float, default=0.33)
    parser.add_argument("--smoke-steps", type=int, default=4)
    parser.add_argument("--samples-per-epoch", type=int, default=8192)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if (
        args.epochs <= 0
        or args.batch_size <= 0
        or args.gradient_accumulation_steps <= 0
        or args.samples_per_epoch <= 0
    ):
        raise ValueError("epochs, batch-size and gradient-accumulation-steps must be positive")
    role_targets = {
        "positive": args.positive_share,
        "negative": args.negative_share,
        "abstention": args.abstention_share,
    }
    if not math.isclose(sum(role_targets.values()), 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise ValueError("positive, negative and abstention shares must sum to 1.0")
    if not 0.30 <= args.pyro_max_share <= 0.35:
        raise ValueError("pyro-max-share must remain between 0.30 and 0.35")
    report = build_preflight_report(
        pointing_root=args.pointing_root,
        multitask_manifest=args.multitask_manifest,
        data_root=args.data_root,
        model_id=args.model_id,
        model_revision=args.model_revision,
        initial_safetensors=args.initial_safetensors,
        backbone_config=args.backbone_config,
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
            "balanced_sampling": args.balanced_sampling,
            "role_targets": role_targets,
            "pyro_max_share": args.pyro_max_share,
            "samples_per_epoch": args.samples_per_epoch,
        },
        "initialization": report["initialization"],
        "initial_safetensors": report["initial_safetensors"],
        "backbone_config": report["backbone_config"],
        "gates": ["masks", "anchor_heatmaps", "visual_abstention", "split_group_isolation"],
        "training_ready": report["training_ready"],
    }
    _write_json(args.output / "training-plan.json", plan)
    if args.command == "plan":
        return
    if not report["training_ready"]:
        raise RuntimeError("DINOv3 training gate failed; provide the canonical multi-task manifest")
    if args.command == "smoke":
        from training.dinov3_adapter import finite_loss_probe

        smoke = finite_loss_probe(
            manifest=args.multitask_manifest.resolve(),
            data_root=args.data_root.resolve(),
            model_id=args.model_id,
            model_revision=args.model_revision,
            image_size=args.image_size,
            batch_size=args.batch_size,
            num_workers=args.num_workers,
            initial_safetensors=args.initial_safetensors,
            backbone_config=args.backbone_config,
            role_targets=role_targets,
            pyro_share=args.pyro_max_share,
            smoke_steps=args.smoke_steps,
            seed=args.seed,
            learning_rate=min(args.learning_rate, 1e-6),
            samples_per_epoch=args.samples_per_epoch,
        )
        _write_json(args.output / "smoke-report.json", smoke)
        print(json.dumps(smoke, ensure_ascii=False, indent=2, sort_keys=True))
        return
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
            image_size=args.image_size,
            num_workers=args.num_workers,
            early_stopping_patience=args.early_stopping_patience,
            initial_safetensors=args.initial_safetensors,
            backbone_config=args.backbone_config,
            balanced_sampling=args.balanced_sampling,
            role_targets=role_targets,
            pyro_share=args.pyro_max_share,
            samples_per_epoch=args.samples_per_epoch,
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
