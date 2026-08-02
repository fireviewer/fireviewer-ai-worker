"""Prepare and run the FireViewer RF-DETR Large challenger.

The input is the frozen COCO conversion of the same four source manifests used
by the published D-FINE run.  The script deliberately keeps the conversion
read-only, writes a provenance record before training, and fails closed when a
dataset or package contract drifts.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_DATASET_ROOT = Path(
    os.environ.get(
        "FIREVIEWER_DETECTION_DATASET_ROOT",
        "data/datasets/fire-smoke-detection-corpus-v1",
    )
)
DEFAULT_OUTPUT = Path("data/training/rfdetr-large-fire-smoke-v1")
EXPECTED_CLASSES = ("flame_visible", "smoke_visible")
EXPECTED_SPLITS = {
    "train": {"images": 114859, "annotations": 155443},
    "valid": {"images": 30406, "annotations": 39895},
    "test": {"images": 25144, "annotations": 34125},
}
EXPECTED_SOURCE_MANIFESTS = (
    "manifests/fasdd/manifest.jsonl",
    "manifests/pyro-sdis/manifest.jsonl",
    "manifests/alarmod/manifest.rtdetr.jsonl",
    "manifests/boreal/manifest.jsonl",
)
MODEL_VARIANTS = {
    "large": {
        "family": "RF-DETR Large",
        "model_class": "RFDETRLarge",
        "pretrain_filename": "rf-detr-large-2026.pth",
        "pretrain_md5": "5cb72153541cbcb9aa6efa26222acc75",
        "profile": "historical_pushed_adapted_to_expanded_corpus",
        "epochs": 3,
        "batch_size": 4,
        "grad_accum_steps": 16,
        "eval_max_dets": 120,
        "run_test": False,
    },
    "small": {
        "family": "RF-DETR Small",
        "model_class": "RFDETRSmall",
        "pretrain_filename": "rf-detr-small.pth",
        "pretrain_md5": "fb37061c1af7bace359c91b723a8d5c1",
        "profile": "historical_standard",
        "epochs": 240,
        "batch_size": 4,
        "grad_accum_steps": 8,
        "eval_max_dets": 300,
        "run_test": True,
    },
}

HISTORICAL_RESOLUTION = 512
HISTORICAL_LEARNING_RATE = 1e-4
HISTORICAL_ENCODER_LEARNING_RATE = 1e-5
HISTORICAL_WEIGHT_DECAY = 1e-4
HISTORICAL_SEED = 420


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _variant_config(variant: str) -> dict[str, Any]:
    return MODEL_VARIANTS[variant]


def _resolve_variant_defaults(args: argparse.Namespace) -> None:
    config = _variant_config(args.variant)
    if args.epochs is None:
        args.epochs = config["epochs"]
    if args.batch_size is None:
        args.batch_size = config["batch_size"]
    if args.grad_accum_steps is None:
        args.grad_accum_steps = config["grad_accum_steps"]
    if args.pretrain_weights is None:
        args.pretrain_weights = args.rf_home / config["pretrain_filename"]


def _check_pretrain_weights(path: Path, expected_md5: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"RF-DETR pretrained weights are missing: {path}")
    actual_md5 = _md5(path)
    if actual_md5 != expected_md5:
        raise ValueError(
            f"RF-DETR pretrained weights MD5 drift: expected {expected_md5}, got {actual_md5}"
        )
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "md5": actual_md5,
        "sha256": _sha256(path),
    }


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _annotation_path(coco_root: Path, split: str) -> Path:
    return coco_root / split / "_annotations.coco.json"


def _check_coco(path: Path, expected: dict[str, int]) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"RF-DETR COCO annotations are missing: {path}")
    value = _json(path)
    images = value.get("images")
    annotations = value.get("annotations")
    categories = value.get("categories")
    if not isinstance(images, list) or len(images) != expected["images"]:
        raise ValueError(f"COCO image count drift in {path}: {len(images or [])}")
    if not isinstance(annotations, list) or len(annotations) != expected["annotations"]:
        raise ValueError(f"COCO annotation count drift in {path}: {len(annotations or [])}")
    if not isinstance(categories, list):
        raise ValueError(f"COCO categories are missing in {path}")
    names = tuple(str(item.get("name")) for item in sorted(categories, key=lambda item: item["id"]))
    if names != EXPECTED_CLASSES:
        raise ValueError(f"COCO class drift in {path}: {names}")
    image_ids = {int(item["id"]) for item in images}
    annotation_image_ids = {int(item["image_id"]) for item in annotations}
    if not annotation_image_ids <= image_ids:
        raise ValueError(f"COCO annotation references an unknown image in {path}")
    category_counts = Counter(int(item["category_id"]) for item in annotations)
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "images": len(images),
        "annotations": len(annotations),
        "categories": list(names),
        "category_counts": dict(sorted(category_counts.items())),
        "negative_images": len(image_ids - annotation_image_ids),
    }


def build_preflight_report(
    dataset_root: Path,
    *,
    model_family: str = "RF-DETR Large",
    pretrain_weights: Path | None = None,
    expected_pretrain_md5: str | None = None,
) -> dict[str, Any]:
    dataset_root = dataset_root.resolve()
    conversion_root = dataset_root / "_rfdetr_coco"
    completion_path = conversion_root / "_conversion_complete.json"
    publication_path = dataset_root / "publication-manifest.json"
    audit_path = dataset_root / "corpus-audit.json"
    errors: list[str] = []
    required = [completion_path, publication_path, audit_path]
    errors.extend(
        f"missing:{path.relative_to(dataset_root)}" for path in required if not path.is_file()
    )
    source_manifests: dict[str, str] = {}
    for relative in EXPECTED_SOURCE_MANIFESTS:
        path = dataset_root / relative
        if not path.is_file():
            errors.append(f"missing:{relative}")
        else:
            source_manifests[relative] = _sha256(path)
    conversion: dict[str, Any] = {}
    split_reports: dict[str, Any] = {}
    pretrain: dict[str, Any] = {}
    if pretrain_weights is not None and expected_pretrain_md5 is not None:
        try:
            pretrain = _check_pretrain_weights(pretrain_weights, expected_pretrain_md5)
        except (FileNotFoundError, ValueError) as exc:
            errors.append(str(exc))
    if not errors:
        completion = _json(completion_path)
        if completion.get("classes") != list(EXPECTED_CLASSES):
            errors.append("conversion_class_map_drift")
        if completion.get("max_samples_per_split") is not None:
            errors.append("conversion_is_sample_limited")
        conversion = {
            "completion_sha256": _sha256(completion_path),
            "prepared_coco_dir": str(conversion_root),
            "source_dataset_dir": str(dataset_root),
        }
        for split, expected in EXPECTED_SPLITS.items():
            try:
                split_reports[split] = _check_coco(
                    _annotation_path(conversion_root, split), expected
                )
            except (FileNotFoundError, ValueError) as exc:
                errors.append(str(exc))
    report = {
        "schema_version": 1,
        "model_family": model_family,
        "role": "benchmark_only_challenger",
        "dataset_root": str(dataset_root),
        "source_manifest_paths": [
            str((dataset_root / item).resolve()) for item in EXPECTED_SOURCE_MANIFESTS
        ],
        "source_manifest_sha256": source_manifests,
        "conversion": conversion,
        "pretrain_weights": pretrain,
        "splits": split_reports,
        "training_errors": errors,
        "training_ready": not errors,
        "promotion_ready": False,
        "promotion_errors": ["frozen_fireviewer_benchmark_missing", "human_review_required"],
    }
    return report


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _build_plan(args: argparse.Namespace, report: dict[str, Any]) -> dict[str, Any]:
    variant = _variant_config(args.variant)
    return {
        "schema_version": 1,
        "model_family": variant["family"],
        "model_class": variant["model_class"],
        "role": "benchmark_only_challenger",
        "dataset": report["conversion"],
        "pretrain_weights": report["pretrain_weights"],
        "classes": list(EXPECTED_CLASSES),
        "hyperparameters": {
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "grad_accum_steps": args.grad_accum_steps,
            "learning_rate": args.learning_rate,
            "encoder_learning_rate": args.encoder_learning_rate,
            "weight_decay": args.weight_decay,
            "resolution": args.resolution,
            "gradient_checkpointing": True,
            "freeze_encoder": False,
            "amp_dtype": "bf16",
            "use_ema": True,
            "checkpoint_interval": 1,
            "num_workers": 0,
            "seed": args.seed,
        },
        "methodology": {
            "training_profile": variant["profile"],
            "frozen_input_conversion": True,
            "resume_policy": "explicit_checkpoint_only",
            "preflight_required": True,
            "windows_progress_bar": "disabled_to_avoid_cp1252_rich_failure",
            "promotion": "benchmark_and_human_gate_required",
        },
    }


def _run_training(args: argparse.Namespace, report: dict[str, Any]) -> None:
    os.environ.setdefault("RF_HOME", str(args.rf_home.resolve()))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    try:
        import rfdetr
    except ImportError as exc:
        raise RuntimeError(
            "RF-DETR package is required; install the pinned training extra first"
        ) from exc
    try:
        package_version = importlib.metadata.version("rfdetr")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("rfdetr package metadata is unavailable") from exc
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    preflight_path = output / "preflight-report.json"
    _write_json(preflight_path, report)
    plan = _build_plan(args, report)
    _write_json(output / "training-plan.json", plan)
    variant = _variant_config(args.variant)
    provenance = {
        "schema_version": 1,
        "model_family": variant["family"],
        "model_class": variant["model_class"],
        "package": {"name": "rfdetr", "version": package_version},
        "dataset": report["conversion"],
        "pretrain_weights": report["pretrain_weights"],
        "source_manifest_sha256": report["source_manifest_sha256"],
        "preflight_sha256": _sha256(preflight_path),
        "args": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
    }
    _write_json(output / "training-provenance.json", provenance)
    model = getattr(rfdetr, variant["model_class"])(
        num_classes=len(EXPECTED_CLASSES),
        gradient_checkpointing=True,
        freeze_encoder=False,
        resolution=args.resolution,
        device="cuda:0",
        pretrain_weights=str(args.pretrain_weights.resolve()),
    )
    train = model.train
    signature = inspect.signature(train)
    parameters = signature.parameters
    requested = {
        "dataset_dir": str(Path(report["conversion"]["prepared_coco_dir"])),
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "grad_accum_steps": args.grad_accum_steps,
        "lr": args.learning_rate,
        "lr_encoder": args.encoder_learning_rate,
        "weight_decay": args.weight_decay,
        "output_dir": str(output),
        "seed": args.seed,
        "class_names": list(EXPECTED_CLASSES),
        "num_workers": 0,
        "amp_dtype": "bf16",
        "use_ema": True,
        "checkpoint_interval": 1,
        "early_stopping": True,
        "early_stopping_patience": 4000 if args.variant == "large" else 500,
        "early_stopping_min_delta": 1e-4,
        "skip_best_epochs": 1,
        "tensorboard": True,
        "wandb": False,
        "mlflow": False,
        "run_test": variant["run_test"],
        "eval_interval": 1,
        "eval_max_dets": variant["eval_max_dets"],
        "log_per_class_metrics": True,
        "augmentation_backend": "cpu",
        "progress_bar": None,
        "save_dataset_grids": False,
        "notes": {
            "project": "FireViewer",
            "dataset": "fireviewer/fire-smoke-detection-corpus-v1",
            "classes": list(EXPECTED_CLASSES),
            "seed": args.seed,
            "training_profile": variant["profile"],
            "rfdetr_variant": args.variant,
            "pretrained_weights_md5": report["pretrain_weights"]["md5"],
        },
    }
    if args.resume is not None:
        requested["resume"] = args.resume
    unsupported = sorted(name for name in requested if name not in parameters and not any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    ))
    if unsupported:
        raise RuntimeError(
            "installed RF-DETR API does not support required arguments: "
            f"{unsupported}"
        )
    train(**requested)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FireViewer RF-DETR Large training")
    parser.add_argument("command", choices=("preflight", "plan", "train"))
    parser.add_argument("--variant", choices=tuple(MODEL_VARIANTS), default="large")
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--grad-accum-steps", type=int)
    parser.add_argument("--learning-rate", type=float, default=HISTORICAL_LEARNING_RATE)
    parser.add_argument(
        "--encoder-learning-rate", type=float, default=HISTORICAL_ENCODER_LEARNING_RATE
    )
    parser.add_argument("--weight-decay", type=float, default=HISTORICAL_WEIGHT_DECAY)
    parser.add_argument("--resolution", type=int, default=HISTORICAL_RESOLUTION)
    parser.add_argument("--seed", type=int, default=HISTORICAL_SEED)
    parser.add_argument("--resume", type=str)
    parser.add_argument(
        "--rf-home",
        type=Path,
        default=Path(os.environ.get("RF_HOME", "models/rfdetr")),
    )
    parser.add_argument("--pretrain-weights", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    _resolve_variant_defaults(args)
    if (
        args.epochs <= 0
        or args.batch_size <= 0
        or args.grad_accum_steps <= 0
        or args.learning_rate <= 0
        or args.encoder_learning_rate <= 0
        or args.weight_decay <= 0
        or args.resolution <= 0
    ):
        raise ValueError("RF-DETR training hyperparameters must be positive")
    variant = _variant_config(args.variant)
    report = build_preflight_report(
        args.dataset_root,
        model_family=variant["family"],
        pretrain_weights=args.pretrain_weights,
        expected_pretrain_md5=variant["pretrain_md5"],
    )
    args.output.mkdir(parents=True, exist_ok=True)
    _write_json(args.output / "preflight-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.command == "preflight":
        if not report["training_ready"]:
            raise SystemExit(2)
        return
    if not report["training_ready"]:
        raise RuntimeError("RF-DETR training gate failed")
    if args.command == "plan":
        _write_json(args.output / "training-plan.json", _build_plan(args, report))
        return
    _run_training(args, report)


if __name__ == "__main__":
    main()
