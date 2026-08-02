"""Full-parameter DINOv3 multi-task adapter for FireViewer manifests."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


class DinoV3MultiTaskDataset:
    """Lazy image/mask loader for the adapted FireWarning manifest."""

    def __init__(self, manifest: Path, data_root: Path, split: str, image_size: int) -> None:
        import torch
        from PIL import Image

        self._torch = torch
        self._image = Image
        self.data_root = data_root.resolve()
        self.image_size = image_size
        self.rows = [
            json.loads(line)
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip()
            and json.loads(line).get("split") == split
        ]
        if not self.rows:
            raise ValueError(f"DINOv3 manifest has no {split} rows")

    def __len__(self) -> int:
        return len(self.rows)

    def _path(self, value: str) -> Path:
        path = (self.data_root / value).resolve()
        if self.data_root not in path.parents:
            raise ValueError(f"manifest path escapes data root: {value}")
        return path

    def __getitem__(self, index: int) -> dict[str, Any]:
        import numpy as np

        row = self.rows[index]
        image = self._image.open(self._path(row["image_relpath"])).convert("RGB")
        mask = self._image.open(self._path(row["mask_relpath"])).convert("L")
        image = image.resize((self.image_size, self.image_size), self._image.Resampling.BILINEAR)
        mask = mask.resize((self.image_size, self.image_size), self._image.Resampling.NEAREST)
        image_tensor = (
            self._torch.from_numpy(np.asarray(image, dtype=np.float32))
            .permute(2, 0, 1)
            / 255.0
        )
        mask_tensor = self._torch.from_numpy((np.asarray(mask) > 0).astype(np.float32))[None]
        heatmap = self._torch.zeros(
            (1, self.image_size, self.image_size), dtype=self._torch.float32
        )
        points = row.get("anchor_points") or []
        for point in points:
            x = min(self.image_size - 1, max(0, round(float(point["x"]) * (self.image_size - 1))))
            y = min(self.image_size - 1, max(0, round(float(point["y"]) * (self.image_size - 1))))
            heatmap[0, y, x] = 1.0
        return {
            "image": image_tensor,
            "mask": mask_tensor,
            "point_heatmap": heatmap,
            "abstention": self._torch.tensor(
                float(row.get("visual_abstention_reason") is not None), dtype=self._torch.float32
            ),
        }


class DinoV3MultiTaskModel:
    """DINOv3 backbone with segmentation, point heatmap and abstention heads."""

    def __init__(self, model_id: str, revision: str, image_size: int) -> None:
        import torch
        from transformers import AutoModel

        class _Network(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.backbone = AutoModel.from_pretrained(model_id, revision=revision, token=True)
                hidden = int(self.backbone.config.hidden_size)
                self.register_tokens = int(getattr(self.backbone.config, "num_register_tokens", 4))
                self.patch_size = int(getattr(self.backbone.config, "patch_size", 16))
                self.segmentation_head = torch.nn.Conv2d(hidden, 1, kernel_size=1)
                self.point_head = torch.nn.Conv2d(hidden, 1, kernel_size=1)
                self.abstention_head = torch.nn.Linear(hidden, 1)

            def _patch_map(self, outputs: Any, height: int, width: int) -> tuple[Any, Any]:
                tokens = outputs.last_hidden_state
                patch_tokens = tokens[:, 1 + self.register_tokens :]
                grid_h = height // self.patch_size
                grid_w = width // self.patch_size
                expected = grid_h * grid_w
                if patch_tokens.shape[1] != expected:
                    raise RuntimeError(
                        f"DINOv3 patch grid mismatch: {patch_tokens.shape[1]} != {expected}"
                    )
                feature_map = patch_tokens.transpose(1, 2).reshape(
                    tokens.shape[0], tokens.shape[2], grid_h, grid_w
                )
                return feature_map, tokens[:, 0]

            def forward(self, images: Any) -> dict[str, Any]:
                outputs = self.backbone(pixel_values=images)
                feature_map, class_token = self._patch_map(
                    outputs, images.shape[-2], images.shape[-1]
                )
                return {
                    "segmentation_logits": torch.nn.functional.interpolate(
                        self.segmentation_head(feature_map),
                        size=images.shape[-2:],
                        mode="bilinear",
                        align_corners=False,
                    ),
                    "point_logits": torch.nn.functional.interpolate(
                        self.point_head(feature_map),
                        size=images.shape[-2:],
                        mode="bilinear",
                        align_corners=False,
                    ),
                    "abstention_logits": self.abstention_head(class_token).squeeze(-1),
                }

        self.network = _Network()
        self.image_size = image_size


def run_training(
    *,
    manifest: Path,
    data_root: Path,
    output: Path,
    model_id: str,
    model_revision: str,
    epochs: int,
    batch_size: int,
    gradient_accumulation_steps: int,
    learning_rate: float,
    seed: int,
    image_size: int,
    num_workers: int,
) -> dict[str, Any]:
    import torch
    from torch.utils.data import DataLoader

    torch.manual_seed(seed)
    output.mkdir(parents=True, exist_ok=True)
    train_set = DinoV3MultiTaskDataset(manifest, data_root, "train", image_size)
    validation_set = DinoV3MultiTaskDataset(manifest, data_root, "validation", image_size)
    train_loader = DataLoader(
        train_set,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
    )
    validation_loader = DataLoader(
        validation_set,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
    )
    model = DinoV3MultiTaskModel(model_id, model_revision, image_size).network
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
    bce = torch.nn.BCEWithLogitsLoss()
    metrics_path = output / "metrics.csv"
    with metrics_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["epoch", "train_loss", "validation_loss"])
        for epoch in range(1, epochs + 1):
            model.train()
            train_loss = 0.0
            optimizer.zero_grad(set_to_none=True)
            for step, batch in enumerate(train_loader, start=1):
                images = batch["image"].to(device)
                outputs = model(images)
                loss = (
                    bce(outputs["segmentation_logits"], batch["mask"].to(device))
                    + bce(outputs["point_logits"], batch["point_heatmap"].to(device))
                    + 0.25 * bce(outputs["abstention_logits"], batch["abstention"].to(device))
                )
                (loss / gradient_accumulation_steps).backward()
                if step % gradient_accumulation_steps == 0 or step == len(train_loader):
                    optimizer.step()
                    optimizer.zero_grad(set_to_none=True)
                train_loss += float(loss.detach().cpu())
            model.eval()
            validation_loss = 0.0
            with torch.no_grad():
                for batch in validation_loader:
                    outputs = model(batch["image"].to(device))
                    validation_loss += float(
                        bce(outputs["segmentation_logits"], batch["mask"].to(device))
                        + bce(outputs["point_logits"], batch["point_heatmap"].to(device))
                        + 0.25
                        * bce(outputs["abstention_logits"], batch["abstention"].to(device))
                    )
            checkpoint = output / "checkpoints" / f"epoch-{epoch:03d}.pt"
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            torch.save({"model": model.state_dict(), "epoch": epoch}, checkpoint)
            writer.writerow(
                [
                    epoch,
                    train_loss / len(train_loader),
                    validation_loss / len(validation_loader),
                ]
            )
            handle.flush()
    return {
        "model_id": model_id,
        "model_revision": model_revision,
        "epochs": epochs,
        "train_rows": len(train_set),
        "validation_rows": len(validation_set),
        "device": str(device),
        "metrics": str(metrics_path),
    }
