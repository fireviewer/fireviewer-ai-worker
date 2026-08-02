from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image
from training.dinov3_adapter import DinoV3MultiTaskDataset


def test_dinov3_dataset_loads_mask_point_and_abstention(tmp_path: Path) -> None:
    image = tmp_path / "image.jpg"
    mask = tmp_path / "mask.png"
    Image.fromarray(np.full((12, 16, 3), 128, dtype=np.uint8)).save(image)
    mask_array = np.zeros((12, 16), dtype=np.uint8)
    mask_array[4:8, 6:10] = 255
    Image.fromarray(mask_array).save(mask)
    manifest = tmp_path / "manifest.jsonl"
    rows = [
        {
            "sample_id": "sample-1",
            "split": "train",
            "image_relpath": "image.jpg",
            "mask_relpath": "mask.png",
            "anchor_points": [{"kind": "smoke_centroid", "x": 0.5, "y": 0.5}],
            "visual_abstention_reason": None,
        }
    ]
    manifest.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    sample = DinoV3MultiTaskDataset(manifest, tmp_path, "train", 32)[0]

    assert tuple(sample["image"].shape) == (3, 32, 32)
    assert tuple(sample["mask"].shape) == (1, 32, 32)
    assert float(sample["point_heatmap"].max()) == 1.0
    assert float(sample["abstention"]) == 0.0
