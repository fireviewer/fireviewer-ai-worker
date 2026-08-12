from __future__ import annotations

from pathlib import Path

import torch
from safetensors import safe_open
from safetensors.torch import load_file
from tools.convert_dinov3_safetensors import convert_checkpoint


def test_convert_checkpoint_preserves_complete_state(tmp_path: Path) -> None:
    source = tmp_path / "checkpoint.pt"
    destination = tmp_path / "model.safetensors"
    state = {
        "backbone.weight": torch.arange(12, dtype=torch.float32).reshape(3, 4),
        "head.bias": torch.tensor([1.0, -1.0]),
    }
    torch.save(
        {
            "schema_version": 2,
            "model": state,
            "epoch": 5,
            "model_revision": "immutable-revision",
            "validation": {"loss": 0.25},
        },
        source,
    )

    report = convert_checkpoint(source, destination)

    restored = load_file(destination)
    assert report["validated_exact"] is True
    assert report["tensor_count"] == 2
    assert restored.keys() == state.keys()
    assert all(torch.equal(restored[key], value) for key, value in state.items())
    with safe_open(destination, framework="pt") as handle:
        metadata = handle.metadata()
    assert metadata is not None
    assert metadata["architecture"] == "DinoV3MultiTaskModel"
    assert metadata["epoch"] == "5"
