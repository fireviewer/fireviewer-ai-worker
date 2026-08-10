"""Full-parameter DINOv3 multi-task training with a DPT-style decoder."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image
from torch import nn

IMAGE_MEAN = torch.tensor((0.485, 0.456, 0.406), dtype=torch.float32)[:, None, None]
IMAGE_STD = torch.tensor((0.229, 0.224, 0.225), dtype=torch.float32)[:, None, None]
PYRO_SDIS_SOURCE_ID = "pyronear-pyro-sdis"
DEFAULT_ROLE_TARGETS = {
    "positive": 0.48,
    "negative": 0.28,
    "abstention": 0.24,
}


def supervision_role(row: dict[str, Any]) -> str:
    if row.get("visual_abstention_reason") is not None:
        return "abstention"
    if str(row.get("annotation_strength")) in {"negative", "temporal_negative"}:
        return "negative"
    return "positive"


def balanced_sampling_weights(
    rows: list[dict[str, Any]],
    *,
    role_targets: dict[str, float] | None = None,
    pyro_source_id: str = PYRO_SDIS_SOURCE_ID,
    pyro_share: float = 0.33,
) -> tuple[torch.Tensor, dict[str, Any]]:
    """Build source-aware sampling probabilities with explicit role margins."""

    targets = dict(role_targets or DEFAULT_ROLE_TARGETS)
    if set(targets) != set(DEFAULT_ROLE_TARGETS):
        raise ValueError(f"role targets must be {sorted(DEFAULT_ROLE_TARGETS)}")
    if any(not math.isfinite(value) or value <= 0.0 for value in targets.values()):
        raise ValueError("role targets must be finite and positive")
    total_target = sum(targets.values())
    if not math.isclose(total_target, 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise ValueError(f"role targets must sum to 1.0, got {total_target}")
    if not 0.0 < pyro_share < 1.0:
        raise ValueError("pyro share must be between zero and one")
    if not rows:
        raise ValueError("cannot balance an empty training split")

    groups: dict[tuple[str, bool, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        role = supervision_role(row)
        source = str(row.get("source_id") or "unknown")
        groups[(role, source == pyro_source_id, source)].append(index)

    probabilities = torch.zeros(len(rows), dtype=torch.double)
    target_origin_mass = {True: pyro_share, False: 1.0 - pyro_share}
    for role, role_target in targets.items():
        present_origins = [
            is_pyro
            for is_pyro in (False, True)
            if any(key[0] == role and key[1] == is_pyro for key in groups)
        ]
        if not present_origins:
            raise ValueError(f"training split has no {role} rows")
        origin_denominator = sum(target_origin_mass[value] for value in present_origins)
        for is_pyro in present_origins:
            cell_target = role_target * target_origin_mass[is_pyro] / origin_denominator
            source_groups = {
                source: indices
                for (group_role, group_is_pyro, source), indices in groups.items()
                if group_role == role and group_is_pyro == is_pyro
            }
            source_scores = {
                source: math.sqrt(len(indices)) for source, indices in source_groups.items()
            }
            score_total = sum(source_scores.values())
            for source, indices in source_groups.items():
                source_target = cell_target * source_scores[source] / score_total
                probabilities[indices] = source_target / len(indices)

    probabilities /= probabilities.sum()
    expected_roles = Counter()
    expected_sources = Counter()
    for probability, row in zip(probabilities.tolist(), rows, strict=True):
        expected_roles[supervision_role(row)] += probability
        expected_sources[str(row.get("source_id") or "unknown")] += probability
    report = {
        "rows": len(rows),
        "role_counts": dict(sorted(Counter(supervision_role(row) for row in rows).items())),
        "source_counts": dict(
            sorted(Counter(str(row.get("source_id") or "unknown") for row in rows).items())
        ),
        "target_role_shares": targets,
        "expected_role_shares": dict(sorted(expected_roles.items())),
        "pyro_source_id": pyro_source_id,
        "pyro_max_share": pyro_share,
        "expected_pyro_share": expected_sources[pyro_source_id],
        "expected_source_shares": dict(sorted(expected_sources.items())),
        "effective_sample_size": float(1.0 / probabilities.square().sum()),
    }
    return probabilities, report


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class DinoV3MultiTaskDataset:
    """Lazy loader for the shared segmentation, point and abstention manifest."""

    def __init__(self, manifest: Path, data_root: Path, split: str, image_size: int) -> None:
        self.data_root = data_root.resolve()
        self.image_size = image_size
        all_rows = [
            json.loads(line)
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.rows = [row for row in all_rows if row.get("split") == split]
        if not self.rows:
            raise ValueError(f"DINOv3 manifest has no {split} rows")

    def __len__(self) -> int:
        return len(self.rows)

    def _path(self, value: str) -> Path:
        path = (self.data_root / value).resolve()
        if path != self.data_root and self.data_root not in path.parents:
            raise ValueError(f"manifest path escapes data root: {value}")
        return path

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.rows[index]
        with Image.open(self._path(str(row["image_relpath"]))) as opened:
            image = opened.convert("RGB").resize(
                (self.image_size, self.image_size), Image.Resampling.BILINEAR
            )
        with Image.open(self._path(str(row["mask_relpath"]))) as opened:
            mask = opened.convert("L").resize(
                (self.image_size, self.image_size), Image.Resampling.NEAREST
            )
        valid_mask_relpath = row.get("valid_mask_relpath")
        if valid_mask_relpath:
            with Image.open(self._path(str(valid_mask_relpath))) as opened:
                valid_mask = opened.convert("L").resize(
                    (self.image_size, self.image_size), Image.Resampling.NEAREST
                )
            valid_mask_tensor = torch.from_numpy(
                (np.asarray(valid_mask) > 0).astype(np.float32).copy()
            )[None]
        else:
            valid_mask_tensor = torch.ones(
                (1, self.image_size, self.image_size), dtype=torch.float32
            )
        image_tensor = (
            torch.from_numpy(np.asarray(image, dtype=np.float32).copy()).permute(2, 0, 1) / 255.0
        )
        image_tensor = (image_tensor - IMAGE_MEAN) / IMAGE_STD
        mask_tensor = torch.from_numpy((np.asarray(mask) > 0).astype(np.float32).copy())[None]
        heatmap = torch.zeros((self.image_size, self.image_size), dtype=torch.float32)
        yy, xx = torch.meshgrid(
            torch.arange(self.image_size, dtype=torch.float32),
            torch.arange(self.image_size, dtype=torch.float32),
            indexing="ij",
        )
        sigma = max(1.5, self.image_size / 64.0)
        points = row.get("anchor_points") or []
        sample_weight = float(row.get("sample_weight", 1.0))
        if not math.isfinite(sample_weight) or sample_weight <= 0.0:
            raise ValueError(f"invalid sample_weight for {row.get('sample_id')}: {sample_weight}")
        for point in points:
            x = min(self.image_size - 1, max(0.0, float(point["x"]) * (self.image_size - 1)))
            y = min(self.image_size - 1, max(0.0, float(point["y"]) * (self.image_size - 1)))
            gaussian = torch.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * sigma**2))
            gaussian = gaussian / gaussian.max().clamp_min(torch.finfo(gaussian.dtype).eps)
            heatmap = torch.maximum(heatmap, gaussian)
        return {
            "image": image_tensor,
            "mask": mask_tensor,
            "valid_mask": valid_mask_tensor,
            "point_heatmap": heatmap[None],
            "has_point": torch.tensor(bool(points), dtype=torch.bool),
            "abstention": torch.tensor(
                float(row.get("visual_abstention_reason") is not None), dtype=torch.float32
            ),
            "sample_id": str(row["sample_id"]),
            "sample_weight": torch.tensor(sample_weight, dtype=torch.float32),
            "source_id": str(row.get("source_id") or "unknown"),
            "supervision_role": supervision_role(row),
        }


class _ResidualConvUnit(nn.Module):
    def __init__(self, features: int) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.GELU(),
            nn.Conv2d(features, features, 3, padding=1, bias=False),
            nn.GroupNorm(32, features),
            nn.GELU(),
            nn.Conv2d(features, features, 3, padding=1, bias=False),
            nn.GroupNorm(32, features),
        )

    def forward(self, value: Any) -> Any:
        return value + self.block(value)


class _FeatureFusionBlock(nn.Module):
    def __init__(self, features: int) -> None:
        super().__init__()
        self.skip_unit = _ResidualConvUnit(features)
        self.output_unit = _ResidualConvUnit(features)

    def forward(self, value: Any, skip: Any) -> Any:
        value = nn.functional.interpolate(
            value, size=skip.shape[-2:], mode="bilinear", align_corners=False
        )
        return self.output_unit(value + self.skip_unit(skip))


class _DPTDecoder(nn.Module):
    def __init__(self, hidden: int, features: int, register_tokens: int, layers: int) -> None:
        super().__init__()
        self.register_tokens = register_tokens
        self.layer_indices = tuple(
            max(1, round(layers * fraction)) for fraction in (0.25, 0.5, 0.75, 1.0)
        )
        self.adapters = nn.ModuleList(
            [nn.Conv2d(hidden, features, kernel_size=1) for _ in self.layer_indices]
        )
        self.fusions = nn.ModuleList([_FeatureFusionBlock(features) for _ in range(3)])

    def _feature_map(self, tokens: Any, grid_h: int, grid_w: int) -> Any:
        patches = tokens[:, 1 + self.register_tokens :]
        if patches.shape[1] != grid_h * grid_w:
            raise RuntimeError(
                f"DINOv3 patch grid mismatch: {patches.shape[1]} != {grid_h * grid_w}"
            )
        return patches.transpose(1, 2).reshape(tokens.shape[0], tokens.shape[2], grid_h, grid_w)

    def forward(self, hidden_states: Any, grid_h: int, grid_w: int) -> Any:
        maps = [
            adapter(self._feature_map(hidden_states[layer], grid_h, grid_w))
            for adapter, layer in zip(self.adapters, self.layer_indices, strict=True)
        ]
        maps[0] = nn.functional.interpolate(
            maps[0], size=(grid_h * 4, grid_w * 4), mode="bilinear", align_corners=False
        )
        maps[1] = nn.functional.interpolate(
            maps[1], size=(grid_h * 2, grid_w * 2), mode="bilinear", align_corners=False
        )
        maps[3] = nn.functional.interpolate(
            maps[3],
            size=(max(1, grid_h // 2), max(1, grid_w // 2)),
            mode="bilinear",
            align_corners=False,
        )
        value = self.fusions[0](maps[3], maps[2])
        value = self.fusions[1](value, maps[1])
        return self.fusions[2](value, maps[0])


class DinoV3MultiTaskModel:
    """DINOv3 ViT-B/16 with shared DPT features and three task heads."""

    def __init__(
        self,
        model_id: str,
        revision: str,
        image_size: int,
        *,
        pretrained_backbone: bool = True,
        backbone_config: Path | str | None = None,
        token: str | bool | None = True,
    ) -> None:
        from transformers import AutoConfig, AutoModel

        class _Network(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                local = Path(model_id).exists()
                load_kwargs = {
                    "revision": None if local else revision,
                    "local_files_only": local,
                    "token": False if local else token,
                }
                if pretrained_backbone:
                    self.backbone = AutoModel.from_pretrained(model_id, **load_kwargs)
                else:
                    if backbone_config is not None:
                        config_data = json.loads(Path(backbone_config).read_text(encoding="utf-8"))
                        model_type = config_data.pop("model_type")
                        config = AutoConfig.for_model(model_type, **config_data)
                    else:
                        config = AutoConfig.from_pretrained(model_id, **load_kwargs)
                    self.backbone = AutoModel.from_config(config)
                hidden = int(self.backbone.config.hidden_size)
                register_tokens = int(getattr(self.backbone.config, "num_register_tokens", 4))
                self.patch_size = int(getattr(self.backbone.config, "patch_size", 16))
                layers = int(getattr(self.backbone.config, "num_hidden_layers", 12))
                features = 256
                self.decoder = _DPTDecoder(hidden, features, register_tokens, layers)
                self.segmentation_head = nn.Sequential(
                    nn.Conv2d(features, 128, 3, padding=1), nn.GELU(), nn.Conv2d(128, 1, 1)
                )
                self.point_head = nn.Sequential(
                    nn.Conv2d(features, 128, 3, padding=1), nn.GELU(), nn.Conv2d(128, 1, 1)
                )
                self.abstention_head = nn.Sequential(nn.LayerNorm(hidden), nn.Linear(hidden, 1))

            def forward(self, images: Any) -> dict[str, Any]:
                outputs = self.backbone(pixel_values=images, output_hidden_states=True)
                if outputs.hidden_states is None:
                    raise RuntimeError("DINOv3 backbone did not return hidden states")
                grid_h = images.shape[-2] // self.patch_size
                grid_w = images.shape[-1] // self.patch_size
                features = self.decoder(outputs.hidden_states, grid_h, grid_w)
                features = nn.functional.interpolate(
                    features, size=images.shape[-2:], mode="bilinear", align_corners=False
                )
                return {
                    "segmentation_logits": self.segmentation_head(features),
                    "point_logits": self.point_head(features),
                    "abstention_logits": self.abstention_head(
                        outputs.last_hidden_state[:, 0]
                    ).squeeze(-1),
                }

        self.network = _Network()
        self.image_size = image_size

    @classmethod
    def from_safetensors(
        cls,
        weights: Path | str,
        *,
        model_id: str,
        revision: str,
        image_size: int = 512,
        backbone_config: Path | str | None = None,
        token: str | bool | None = True,
    ) -> DinoV3MultiTaskModel:
        """Build the architecture without base weights and load the complete safe state."""

        from safetensors.torch import load_file

        instance = cls(
            model_id,
            revision,
            image_size,
            pretrained_backbone=False,
            backbone_config=backbone_config,
            token=token,
        )
        state = load_file(str(weights), device="cpu")
        instance.network.load_state_dict(state, strict=True)
        instance.network.eval()
        return instance


def _dice_loss(logits: Any, target: Any, valid_mask: Any, *, reduction: str = "mean") -> Any:
    probability = logits.sigmoid()
    intersection = (probability * target * valid_mask).sum(dim=(1, 2, 3))
    denominator = (probability * valid_mask).sum(dim=(1, 2, 3)) + (target * valid_mask).sum(
        dim=(1, 2, 3)
    )
    values = 1.0 - (2.0 * intersection + 1.0) / (denominator + 1.0)
    if reduction == "none":
        return values
    if reduction != "mean":
        raise ValueError(f"unsupported dice reduction: {reduction}")
    return values.mean()


def _point_localization_loss(
    logits: Any,
    target: Any,
    valid_mask: Any,
    has_point: Any,
    *,
    reduction: str = "mean",
) -> Any:
    batch_size, _, height, width = logits.shape
    valid = valid_mask.flatten(1)
    flat_logits = logits.flatten(1).masked_fill(valid <= 0, -1e4)
    flat_target = target.flatten(1) * valid
    positive = has_point.bool()
    losses = torch.zeros(batch_size, dtype=torch.float32, device=logits.device)
    if bool(positive.any()):
        positive_logits = flat_logits[positive].float()
        target_distribution = flat_target[positive]
        target_distribution = target_distribution / target_distribution.sum(
            dim=1, keepdim=True
        ).clamp_min(1e-8)
        log_probability = nn.functional.log_softmax(positive_logits, dim=1)
        kl = nn.functional.kl_div(log_probability, target_distribution, reduction="none").sum(
            dim=1
        ) / math.log(height * width)
        probability = log_probability.exp()
        yy, xx = torch.meshgrid(
            torch.linspace(0.0, 1.0, height, device=logits.device),
            torch.linspace(0.0, 1.0, width, device=logits.device),
            indexing="ij",
        )
        coordinates = torch.stack((xx.flatten(), yy.flatten()), dim=1)
        predicted_xy = probability @ coordinates
        target_xy = target_distribution @ coordinates
        coordinate = nn.functional.smooth_l1_loss(
            predicted_xy, target_xy, beta=0.05, reduction="none"
        ).mean(dim=1)
        losses[positive] = (kl + 5.0 * coordinate).float()
    negative = ~positive
    if bool(negative.any()):
        negative_logits = logits[negative].float()
        negative_valid = valid_mask[negative]
        negative_bce = nn.functional.binary_cross_entropy_with_logits(
            negative_logits, torch.zeros_like(negative_logits), reduction="none"
        )
        losses[negative] = (
            0.1
            * (negative_bce * negative_valid).flatten(1).sum(dim=1)
            / negative_valid.flatten(1).sum(dim=1).clamp_min(1.0)
        ).float()
    if reduction == "none":
        return losses
    if reduction != "mean":
        raise ValueError(f"unsupported point reduction: {reduction}")
    return losses.mean()


def _weighted_mean(values: torch.Tensor, weights: torch.Tensor) -> torch.Tensor:
    return (values * weights).sum() / weights.sum().clamp_min(torch.finfo(values.dtype).eps)


def _losses(
    outputs: dict[str, Any],
    batch: dict[str, Any],
    device: torch.device,
    *,
    apply_sample_weights: bool = True,
) -> dict[str, Any]:
    mask = batch["mask"].to(device, non_blocking=True)
    valid_mask = batch["valid_mask"].to(device, non_blocking=True)
    heatmap = batch["point_heatmap"].to(device, non_blocking=True)
    abstention = batch["abstention"].to(device, non_blocking=True)
    has_point = batch["has_point"].to(device, non_blocking=True)
    if apply_sample_weights and "sample_weight" in batch:
        sample_weight = batch["sample_weight"].to(device, non_blocking=True).float()
    else:
        sample_weight = torch.ones(mask.shape[0], dtype=torch.float32, device=device)
    segmentation_pixels = nn.functional.binary_cross_entropy_with_logits(
        outputs["segmentation_logits"], mask, reduction="none"
    )
    segmentation_per_sample = (segmentation_pixels * valid_mask).flatten(1).sum(
        dim=1
    ) / valid_mask.flatten(1).sum(dim=1).clamp_min(1.0) + _dice_loss(
        outputs["segmentation_logits"], mask, valid_mask, reduction="none"
    )
    point_per_sample = _point_localization_loss(
        outputs["point_logits"], heatmap, valid_mask, has_point, reduction="none"
    )
    abstention_per_sample = nn.functional.binary_cross_entropy_with_logits(
        outputs["abstention_logits"], abstention, reduction="none"
    )
    segmentation = _weighted_mean(segmentation_per_sample, sample_weight)
    point = _weighted_mean(point_per_sample, sample_weight)
    abstention_loss = _weighted_mean(abstention_per_sample, sample_weight)
    return {
        "loss": segmentation + 0.5 * point + 0.25 * abstention_loss,
        "segmentation_loss": segmentation,
        "point_loss": point,
        "abstention_loss": abstention_loss,
    }


def _build_network(
    *,
    model_id: str,
    model_revision: str,
    image_size: int,
    initial_safetensors: Path | None = None,
    backbone_config: Path | None = None,
) -> tuple[nn.Module, str]:
    if initial_safetensors is not None:
        if not initial_safetensors.is_file():
            raise FileNotFoundError(initial_safetensors)
        if backbone_config is None or not backbone_config.is_file():
            raise FileNotFoundError("backbone_config is required with initial_safetensors")
        wrapped = DinoV3MultiTaskModel.from_safetensors(
            initial_safetensors,
            model_id=model_id,
            revision=model_revision,
            image_size=image_size,
            backbone_config=backbone_config,
            token=False,
        )
        return wrapped.network, "complete_v3_safetensors"
    return (
        DinoV3MultiTaskModel(model_id, model_revision, image_size).network,
        "immutable_base_pretrained",
    )


def _balanced_sampler(
    dataset: DinoV3MultiTaskDataset,
    *,
    seed: int,
    role_targets: dict[str, float],
    pyro_share: float,
    samples_per_epoch: int | None = None,
) -> tuple[Any, dict[str, Any]]:
    from torch.utils.data import WeightedRandomSampler

    weights, report = balanced_sampling_weights(
        dataset.rows,
        role_targets=role_targets,
        pyro_share=pyro_share,
    )
    generator = torch.Generator()
    generator.manual_seed(seed)
    epoch_samples = samples_per_epoch or len(dataset)
    if epoch_samples <= 0:
        raise ValueError("samples_per_epoch must be positive")
    sampler = WeightedRandomSampler(
        weights,
        num_samples=epoch_samples,
        replacement=True,
        generator=generator,
    )
    return sampler, {**report, "samples_per_epoch": epoch_samples}


def _controlled_smoke_indices(rows: list[dict[str, Any]], sampled_indices: list[int]) -> list[int]:
    """Force smoke coverage of every supervision role before sampled draws."""

    required_roles = tuple(DEFAULT_ROLE_TARGETS)
    if len(sampled_indices) < len(required_roles):
        raise ValueError(
            f"smoke requires at least {len(required_roles)} samples to cover every role"
        )
    coverage: list[int] = []
    for role in required_roles:
        try:
            coverage.append(
                next(index for index, row in enumerate(rows) if supervision_role(row) == role)
            )
        except StopIteration as exc:
            raise ValueError(f"training split has no {role} row for controlled smoke") from exc
    return coverage + sampled_indices[len(coverage) :]


def finite_loss_probe(
    *,
    manifest: Path,
    data_root: Path,
    model_id: str,
    model_revision: str,
    image_size: int,
    batch_size: int,
    num_workers: int,
    initial_safetensors: Path | None = None,
    backbone_config: Path | None = None,
    role_targets: dict[str, float] | None = None,
    pyro_share: float = 0.33,
    smoke_steps: int = 4,
    seed: int = 42,
    learning_rate: float = 1e-6,
    samples_per_epoch: int | None = None,
) -> dict[str, Any]:
    from torch.utils.data import DataLoader

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the DINOv3 finite-loss probe")
    if smoke_steps <= 0:
        raise ValueError("smoke_steps must be positive")
    dataset = DinoV3MultiTaskDataset(manifest, data_root, "train", image_size)
    targets = dict(role_targets or DEFAULT_ROLE_TARGETS)
    sampler, sampling_report = _balanced_sampler(
        dataset,
        seed=seed,
        role_targets=targets,
        pyro_share=pyro_share,
        samples_per_epoch=samples_per_epoch,
    )
    smoke_sample_count = smoke_steps * batch_size
    sampler_iterator = iter(sampler)
    sampled_indices = [next(sampler_iterator) for _ in range(smoke_sample_count)]
    smoke_indices = _controlled_smoke_indices(dataset.rows, sampled_indices)
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        sampler=smoke_indices,
        num_workers=num_workers,
        pin_memory=True,
        persistent_workers=num_workers > 0,
    )
    device = torch.device("cuda")
    torch.cuda.reset_peak_memory_stats(device)
    model, initialization = _build_network(
        model_id=model_id,
        model_revision=model_revision,
        image_size=image_size,
        initial_safetensors=initial_safetensors,
        backbone_config=backbone_config,
    )
    model.to(device).train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=0.05)
    loss_history: list[dict[str, float]] = []
    sample_ids: list[str] = []
    observed_roles: Counter[str] = Counter()
    observed_sources: Counter[str] = Counter()
    gradient_tensors = 0
    all_finite = True
    for step, batch in enumerate(loader, 1):
        if step > smoke_steps:
            break
        images = batch["image"].to(device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            losses = _losses(model(images), batch, device, apply_sample_weights=True)
        if not all(bool(torch.isfinite(value).item()) for value in losses.values()):
            raise RuntimeError(f"DINOv3 smoke produced non-finite loss at step {step}")
        losses["loss"].backward()
        gradients = [
            parameter.grad for parameter in model.parameters() if parameter.grad is not None
        ]
        gradient_tensors = max(gradient_tensors, len(gradients))
        step_finite = bool(gradients) and all(
            bool(torch.isfinite(gradient).all().item()) for gradient in gradients
        )
        all_finite &= step_finite
        if not step_finite:
            raise RuntimeError(f"DINOv3 smoke produced non-finite gradients at step {step}")
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        loss_history.append({name: float(value.detach().cpu()) for name, value in losses.items()})
        sample_ids.extend(str(value) for value in batch["sample_id"])
        observed_roles.update(str(value) for value in batch["supervision_role"])
        observed_sources.update(str(value) for value in batch["source_id"])
    if len(loss_history) != smoke_steps:
        raise RuntimeError(f"smoke produced {len(loss_history)} steps instead of {smoke_steps}")
    return {
        "passed": True,
        "device": str(device),
        "batch_size": batch_size,
        "image_size": image_size,
        "smoke_steps": smoke_steps,
        "sample_ids": sample_ids,
        "loss_history": loss_history,
        "gradient_tensors": gradient_tensors,
        "all_gradients_finite": all_finite,
        "peak_vram_bytes": torch.cuda.max_memory_allocated(device),
        "initialization": initialization,
        "initial_weights": initial_safetensors.name if initial_safetensors else None,
        "sampling": sampling_report,
        "observed_roles": dict(sorted(observed_roles.items())),
        "observed_sources": dict(sorted(observed_sources.items())),
        "trainable_parameters": sum(
            parameter.numel() for parameter in model.parameters() if parameter.requires_grad
        ),
    }


def _metric_state() -> dict[str, float]:
    return {
        "rows": 0.0,
        "intersection": 0.0,
        "union": 0.0,
        "dice_numerator": 0.0,
        "dice_denominator": 0.0,
        "target_foreground": 0.0,
        "valid_pixels": 0.0,
        "point_hits": 0.0,
        "point_center_hits": 0.0,
        "point_rows": 0.0,
        "abstention_correct": 0.0,
        "abstention_rows": 0.0,
    }


def _finalize_metric_state(state: dict[str, float]) -> dict[str, Any]:
    rows = state["rows"]
    point_rows = state["point_rows"]
    abstention_rows = state["abstention_rows"]
    return {
        "rows": int(rows),
        "iou": state["intersection"] / max(1.0, state["union"]),
        "dice": state["dice_numerator"] / max(1.0, state["dice_denominator"]),
        "point_pck10": state["point_hits"] / max(1.0, point_rows),
        "point_rows": int(point_rows),
        "abstention_accuracy": state["abstention_correct"] / max(1.0, rows),
        "abstention_rows": int(abstention_rows),
        "baselines": {
            "always_abstain_accuracy": abstention_rows / max(1.0, rows),
            "always_not_abstain_accuracy": (rows - abstention_rows) / max(1.0, rows),
            "point_center_pck10": state["point_center_hits"] / max(1.0, point_rows),
            "segmentation_all_background_iou": (0.0 if state["target_foreground"] > 0.0 else 1.0),
            "segmentation_foreground_fraction": state["target_foreground"]
            / max(1.0, state["valid_pixels"]),
        },
    }


@torch.no_grad()
def _evaluate(model: nn.Module, loader: Any, device: torch.device) -> dict[str, Any]:
    model.eval()
    loss_totals = {
        name: 0.0 for name in ("loss", "segmentation_loss", "point_loss", "abstention_loss")
    }
    loss_rows = 0
    overall = _metric_state()
    per_source: dict[str, dict[str, float]] = defaultdict(_metric_state)
    per_role: dict[str, dict[str, float]] = defaultdict(_metric_state)
    for batch in loader:
        images = batch["image"].to(device, non_blocking=True)
        with torch.autocast(
            device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"
        ):
            outputs = model(images)
            losses = _losses(outputs, batch, device, apply_sample_weights=False)
        batch_rows = images.shape[0]
        for name, value in losses.items():
            loss_totals[name] += float(value.detach().cpu()) * batch_rows
        loss_rows += batch_rows
        predicted = outputs["segmentation_logits"].sigmoid() >= 0.5
        target = batch["mask"].to(device, non_blocking=True) > 0.5
        valid = batch["valid_mask"].to(device, non_blocking=True) > 0.5
        predicted &= valid
        target &= valid
        intersections = (predicted & target).flatten(1).sum(dim=1).cpu().tolist()
        unions = (predicted | target).flatten(1).sum(dim=1).cpu().tolist()
        predicted_pixels = predicted.flatten(1).sum(dim=1).cpu().tolist()
        target_pixels = target.flatten(1).sum(dim=1).cpu().tolist()
        valid_pixels = valid.flatten(1).sum(dim=1).cpu().tolist()
        predicted_flat = outputs["point_logits"].flatten(1).argmax(dim=1)
        target_flat = batch["point_heatmap"].to(device, non_blocking=True).flatten(1).argmax(dim=1)
        width = outputs["point_logits"].shape[-1]
        height = outputs["point_logits"].shape[-2]
        pred_xy = torch.stack((predicted_flat % width, predicted_flat // width), dim=1).float()
        target_xy = torch.stack((target_flat % width, target_flat // width), dim=1).float()
        normalized_error = torch.linalg.vector_norm(pred_xy - target_xy, dim=1) / (
            math.sqrt(2.0) * width
        )
        has_point = batch["has_point"].to(device)
        point_hits = ((normalized_error <= 0.10) & has_point).cpu().tolist()
        center = torch.tensor([(width - 1) / 2.0, (height - 1) / 2.0], device=device)
        center_error = torch.linalg.vector_norm(target_xy - center, dim=1) / (
            math.sqrt(2.0) * width
        )
        center_hits = ((center_error <= 0.10) & has_point).cpu().tolist()
        has_points = has_point.cpu().tolist()
        abstention_pred = outputs["abstention_logits"].sigmoid() >= 0.5
        abstention_target = batch["abstention"].to(device) >= 0.5
        abstention_correct = (abstention_pred == abstention_target).cpu().tolist()
        abstentions = abstention_target.cpu().tolist()
        for index in range(batch_rows):
            states = (
                overall,
                per_source[str(batch["source_id"][index])],
                per_role[str(batch["supervision_role"][index])],
            )
            for state in states:
                state["rows"] += 1
                state["intersection"] += float(intersections[index])
                state["union"] += float(unions[index])
                state["dice_numerator"] += 2.0 * float(intersections[index])
                state["dice_denominator"] += float(predicted_pixels[index] + target_pixels[index])
                state["target_foreground"] += float(target_pixels[index])
                state["valid_pixels"] += float(valid_pixels[index])
                state["point_hits"] += float(point_hits[index])
                state["point_center_hits"] += float(center_hits[index])
                state["point_rows"] += float(has_points[index])
                state["abstention_correct"] += float(abstention_correct[index])
                state["abstention_rows"] += float(abstentions[index])
    metrics = _finalize_metric_state(overall)
    return {
        **{name: value / max(1, loss_rows) for name, value in loss_totals.items()},
        **metrics,
        "source_metrics": {
            source: _finalize_metric_state(state) for source, state in sorted(per_source.items())
        },
        "role_metrics": {
            role: _finalize_metric_state(state) for role, state in sorted(per_role.items())
        },
    }


def _atomic_torch_save(value: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    torch.save(value, temporary)
    os.replace(temporary, path)


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
    early_stopping_patience: int = 8,
    initial_safetensors: Path | None = None,
    backbone_config: Path | None = None,
    balanced_sampling: bool = True,
    role_targets: dict[str, float] | None = None,
    pyro_share: float = 0.33,
    samples_per_epoch: int | None = None,
) -> dict[str, Any]:
    from torch.utils.data import DataLoader

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    output.mkdir(parents=True, exist_ok=True)
    datasets = {
        split: DinoV3MultiTaskDataset(manifest, data_root, split, image_size)
        for split in ("train", "validation", "test")
    }
    targets = dict(role_targets or DEFAULT_ROLE_TARGETS)
    sampler = None
    sampling_report: dict[str, Any] = {
        "enabled": False,
        "rows": len(datasets["train"]),
    }
    if balanced_sampling:
        sampler, sampling_report = _balanced_sampler(
            datasets["train"],
            seed=seed,
            role_targets=targets,
            pyro_share=pyro_share,
            samples_per_epoch=samples_per_epoch,
        )
        sampling_report = {"enabled": True, **sampling_report}
    loaders = {
        "train": DataLoader(
            datasets["train"],
            batch_size=batch_size,
            sampler=sampler,
            shuffle=not balanced_sampling,
            num_workers=num_workers,
            persistent_workers=num_workers > 0,
            pin_memory=torch.cuda.is_available(),
        ),
        **{
            split: DataLoader(
                datasets[split],
                batch_size=batch_size,
                shuffle=False,
                num_workers=num_workers,
                persistent_workers=num_workers > 0,
                pin_memory=torch.cuda.is_available(),
            )
            for split in ("validation", "test")
        },
    }
    model, initialization = _build_network(
        model_id=model_id,
        model_revision=model_revision,
        image_size=image_size,
        initial_safetensors=initial_safetensors,
        backbone_config=backbone_config,
    )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type != "cuda":
        raise RuntimeError("CUDA is required for the full DINOv3 multi-task train")
    model.to(device)
    backbone = list(model.backbone.parameters())
    heads = [
        parameter
        for name, parameter in model.named_parameters()
        if not name.startswith("backbone.")
    ]
    optimizer = torch.optim.AdamW(
        [
            {"params": backbone, "lr": learning_rate},
            {"params": heads, "lr": learning_rate * 5.0},
        ],
        weight_decay=0.05,
    )
    updates_per_epoch = math.ceil(len(loaders["train"]) / gradient_accumulation_steps)
    total_updates = max(1, epochs * updates_per_epoch)
    warmup_updates = max(1, round(total_updates * 0.1))

    def schedule(step: int) -> float:
        if step < warmup_updates:
            return (step + 1) / warmup_updates
        progress = (step - warmup_updates) / max(1, total_updates - warmup_updates)
        return 0.5 * (1.0 + math.cos(math.pi * min(1.0, progress)))

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, schedule)
    checkpoint_dir = output / "checkpoints"
    best_path = checkpoint_dir / "best.pt"
    last_path = checkpoint_dir / "last.pt"
    start_epoch = 1
    best_loss = math.inf
    best_epoch = 0
    stale_epochs = 0
    global_step = 0
    if last_path.is_file():
        state = torch.load(last_path, map_location="cpu", weights_only=False)
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"])
        start_epoch = int(state["epoch"]) + 1
        best_loss = float(state["best_loss"])
        best_epoch = int(state["best_epoch"])
        stale_epochs = int(state["stale_epochs"])
        global_step = int(state["global_step"])
        initialization = "resume_last_checkpoint"
    (output / "sampling-report.json").write_text(
        json.dumps(sampling_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metrics_path = output / "metrics.csv"
    append = start_epoch > 1 and metrics_path.is_file()
    columns = [
        "epoch",
        "train_loss",
        "validation_loss",
        "validation_iou",
        "validation_dice",
        "validation_point_pck10",
        "validation_abstention_accuracy",
        "validation_baselines_json",
        "validation_source_metrics_json",
        "validation_role_metrics_json",
        "learning_rate",
    ]
    with metrics_path.open("a" if append else "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        if not append:
            writer.writeheader()
        for epoch in range(start_epoch, epochs + 1):
            if sampler is not None and sampler.generator is not None:
                sampler.generator.manual_seed(seed + epoch)
            model.train()
            optimizer.zero_grad(set_to_none=True)
            train_loss = 0.0
            for step, batch in enumerate(loaders["train"], 1):
                images = batch["image"].to(device, non_blocking=True)
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    losses = _losses(model(images), batch, device, apply_sample_weights=True)
                    scaled = losses["loss"] / gradient_accumulation_steps
                if not bool(torch.isfinite(scaled).item()):
                    raise RuntimeError(f"non-finite DINOv3 loss at epoch {epoch}, step {step}")
                scaled.backward()
                if step % gradient_accumulation_steps == 0 or step == len(loaders["train"]):
                    nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    optimizer.step()
                    scheduler.step()
                    optimizer.zero_grad(set_to_none=True)
                    global_step += 1
                train_loss += float(losses["loss"].detach().cpu())
            validation = _evaluate(model, loaders["validation"], device)
            row = {
                "epoch": epoch,
                "train_loss": train_loss / len(loaders["train"]),
                "validation_loss": validation["loss"],
                "validation_iou": validation["iou"],
                "validation_dice": validation["dice"],
                "validation_point_pck10": validation["point_pck10"],
                "validation_abstention_accuracy": validation["abstention_accuracy"],
                "validation_baselines_json": json.dumps(
                    validation["baselines"], sort_keys=True, allow_nan=False
                ),
                "validation_source_metrics_json": json.dumps(
                    validation["source_metrics"], sort_keys=True, allow_nan=False
                ),
                "validation_role_metrics_json": json.dumps(
                    validation["role_metrics"], sort_keys=True, allow_nan=False
                ),
                "learning_rate": optimizer.param_groups[0]["lr"],
            }
            writer.writerow(row)
            handle.flush()
            if validation["loss"] < best_loss:
                best_loss = validation["loss"]
                best_epoch = epoch
                stale_epochs = 0
                _atomic_torch_save(
                    {
                        "schema_version": 2,
                        "model": model.state_dict(),
                        "epoch": epoch,
                        "validation": validation,
                        "model_revision": model_revision,
                        "manifest_sha256": _sha256(manifest),
                    },
                    best_path,
                )
            else:
                stale_epochs += 1
            _atomic_torch_save(
                {
                    "schema_version": 2,
                    "model": model.state_dict(),
                    "optimizer": optimizer.state_dict(),
                    "scheduler": scheduler.state_dict(),
                    "epoch": epoch,
                    "global_step": global_step,
                    "best_loss": best_loss,
                    "best_epoch": best_epoch,
                    "stale_epochs": stale_epochs,
                },
                last_path,
            )
            if stale_epochs >= early_stopping_patience:
                break
    if not best_path.is_file():
        raise RuntimeError("DINOv3 train ended without a best checkpoint")
    best_state = torch.load(best_path, map_location="cpu", weights_only=False)
    model.load_state_dict(best_state["model"])
    model.to(device)
    test_metrics = _evaluate(model, loaders["test"], device)
    result = {
        "schema_version": 2,
        "model_id": model_id,
        "model_revision": model_revision,
        "device": str(device),
        "initialization": initialization,
        "initial_weights": initial_safetensors.name if initial_safetensors else None,
        "balanced_sampling": balanced_sampling,
        "sampling": sampling_report,
        "train_rows": len(datasets["train"]),
        "validation_rows": len(datasets["validation"]),
        "test_rows": len(datasets["test"]),
        "epochs_requested": epochs,
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "test_metrics": test_metrics,
        "best_checkpoint": str(best_path),
        "best_checkpoint_sha256": _sha256(best_path),
        "metrics": str(metrics_path),
    }
    return result
