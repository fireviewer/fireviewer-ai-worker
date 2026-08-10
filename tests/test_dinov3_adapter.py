from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image
from training.dinov3_adapter import (
    DinoV3MultiTaskDataset,
    _evaluate,
    _losses,
    _point_localization_loss,
    balanced_sampling_weights,
)


def test_dinov3_dataset_loads_mask_point_and_abstention(tmp_path: Path) -> None:
    image = tmp_path / "image.jpg"
    mask = tmp_path / "mask.png"
    valid_mask = tmp_path / "valid-mask.png"
    Image.fromarray(np.full((12, 16, 3), 128, dtype=np.uint8)).save(image)
    mask_array = np.zeros((12, 16), dtype=np.uint8)
    mask_array[4:8, 6:10] = 255
    Image.fromarray(mask_array).save(mask)
    valid_array = np.zeros((12, 16), dtype=np.uint8)
    valid_array[:, 2:14] = 255
    Image.fromarray(valid_array).save(valid_mask)
    manifest = tmp_path / "manifest.jsonl"
    rows = [
        {
            "sample_id": "sample-1",
            "split": "train",
            "image_relpath": "image.jpg",
            "mask_relpath": "mask.png",
            "valid_mask_relpath": "valid-mask.png",
            "anchor_points": [{"kind": "smoke_centroid", "x": 0.5, "y": 0.5}],
            "visual_abstention_reason": None,
            "annotation_strength": "strong",
            "sample_weight": 4.0,
            "source_id": "camp-swift",
        }
    ]
    manifest.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    sample = DinoV3MultiTaskDataset(manifest, tmp_path, "train", 32)[0]

    assert tuple(sample["image"].shape) == (3, 32, 32)
    assert tuple(sample["mask"].shape) == (1, 32, 32)
    assert tuple(sample["valid_mask"].shape) == (1, 32, 32)
    assert 0.0 < float(sample["valid_mask"].mean()) < 1.0
    assert float(sample["point_heatmap"].max()) == 1.0
    assert float(sample["abstention"]) == 0.0
    assert float(sample["sample_weight"]) == 4.0
    assert sample["source_id"] == "camp-swift"
    assert sample["supervision_role"] == "positive"


def test_point_localization_loss_prefers_the_target_location() -> None:
    target = torch.zeros((1, 1, 8, 8), dtype=torch.float32)
    target[0, 0, 2, 5] = 1.0
    valid = torch.ones_like(target)
    has_point = torch.tensor([True])
    correct = torch.full_like(target, -4.0)
    correct[0, 0, 2, 5] = 4.0
    wrong = torch.full_like(target, -4.0)
    wrong[0, 0, 6, 1] = 4.0
    correct_loss = _point_localization_loss(correct, target, valid, has_point)
    wrong_loss = _point_localization_loss(wrong, target, valid, has_point)
    assert float(correct_loss) < float(wrong_loss)


def test_point_localization_loss_accepts_bfloat16_logits() -> None:
    target = torch.zeros((2, 1, 8, 8), dtype=torch.float32)
    target[0, 0, 2, 5] = 1.0
    valid = torch.ones_like(target)
    logits = torch.zeros_like(target, dtype=torch.bfloat16)

    loss = _point_localization_loss(
        logits,
        target,
        valid,
        torch.tensor([True, False]),
    )

    assert loss.dtype == torch.float32
    assert torch.isfinite(loss)


def test_balanced_sampling_enforces_role_targets_and_pyro_cap() -> None:
    rows = []
    for role, count in (("positive", 10), ("negative", 20), ("abstention", 30)):
        for is_pyro in (False, True):
            for _index in range(count):
                row = {
                    "source_id": "pyronear-pyro-sdis" if is_pyro else "firestereo",
                    "annotation_strength": "strong",
                    "visual_abstention_reason": None,
                }
                if role == "negative":
                    row["annotation_strength"] = "negative"
                if role == "abstention":
                    row["visual_abstention_reason"] = "ambiguous"
                rows.append(row)

    weights, report = balanced_sampling_weights(
        rows,
        role_targets={"positive": 0.48, "negative": 0.28, "abstention": 0.24},
        pyro_share=0.35,
    )

    assert torch.isclose(weights.sum(), torch.tensor(1.0, dtype=torch.double))
    assert report["expected_role_shares"] == pytest.approx(
        {"abstention": 0.24, "negative": 0.28, "positive": 0.48}
    )
    assert abs(report["expected_pyro_share"] - 0.35) < 1e-12


def test_controlled_smoke_indices_cover_every_role() -> None:
    from training.dinov3_adapter import _controlled_smoke_indices, supervision_role

    rows = [
        {"sample_id": "positive", "annotation_strength": "strong"},
        {"sample_id": "negative", "annotation_strength": "negative"},
        {
            "sample_id": "abstention",
            "annotation_strength": "weak",
            "visual_abstention_reason": "not_visible",
        },
        {"sample_id": "extra", "annotation_strength": "strong"},
    ]

    indices = _controlled_smoke_indices(rows, [0, 0, 0, 3])

    assert {supervision_role(rows[index]) for index in indices} == {
        "positive",
        "negative",
        "abstention",
    }
    assert indices[-1] == 3


def test_sample_weights_are_applied_to_losses() -> None:
    outputs = {
        "segmentation_logits": torch.zeros((2, 1, 4, 4)),
        "point_logits": torch.zeros((2, 1, 4, 4)),
        "abstention_logits": torch.zeros(2),
    }
    mask = torch.zeros((2, 1, 4, 4))
    mask[0] = 1.0
    batch = {
        "mask": mask,
        "valid_mask": torch.ones_like(mask),
        "point_heatmap": torch.zeros_like(mask),
        "has_point": torch.tensor([False, False]),
        "abstention": torch.tensor([0.0, 0.0]),
        "sample_weight": torch.tensor([1.0, 10.0]),
    }

    weighted = _losses(outputs, batch, torch.device("cpu"), apply_sample_weights=True)
    unweighted = _losses(outputs, batch, torch.device("cpu"), apply_sample_weights=False)

    assert float(weighted["segmentation_loss"]) > float(unweighted["segmentation_loss"])


def test_evaluation_reports_source_role_and_trivial_baselines() -> None:
    class DummyModel(torch.nn.Module):
        def forward(self, images: torch.Tensor) -> dict[str, torch.Tensor]:
            batch, _, height, width = images.shape
            return {
                "segmentation_logits": torch.zeros((batch, 1, height, width)),
                "point_logits": torch.zeros((batch, 1, height, width)),
                "abstention_logits": torch.zeros(batch),
            }

    rows = []
    for index in range(4):
        heatmap = torch.zeros((1, 8, 8))
        heatmap[0, 4, 4] = 1.0
        rows.append(
            {
                "image": torch.zeros((3, 8, 8)),
                "mask": torch.zeros((1, 8, 8)),
                "valid_mask": torch.ones((1, 8, 8)),
                "point_heatmap": heatmap,
                "has_point": torch.tensor(index < 2),
                "abstention": torch.tensor(float(index >= 2)),
                "sample_weight": torch.tensor(1.0),
                "sample_id": f"sample-{index}",
                "source_id": "source-a" if index % 2 == 0 else "source-b",
                "supervision_role": "positive" if index < 2 else "abstention",
            }
        )
    loader = torch.utils.data.DataLoader(rows, batch_size=2)

    metrics = _evaluate(DummyModel(), loader, torch.device("cpu"))

    assert set(metrics["source_metrics"]) == {"source-a", "source-b"}
    assert set(metrics["role_metrics"]) == {"abstention", "positive"}
    assert metrics["baselines"]["always_abstain_accuracy"] == 0.5
    assert metrics["baselines"]["always_not_abstain_accuracy"] == 0.5
