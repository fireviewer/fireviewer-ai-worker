from __future__ import annotations

import json
from pathlib import Path

from firewarning_worker.transformers_adapters import _qwen_memory_limits

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_default_qwen_budget_matches_the_frozen_a40_stack(monkeypatch) -> None:
    monkeypatch.delenv("FW_QWEN_GPU_MEMORY_GIB", raising=False)
    monkeypatch.delenv("FW_QWEN_CPU_MEMORY_GIB", raising=False)

    assert _qwen_memory_limits() == {0: "44GiB", "cpu": "48GiB"}


def test_pod_and_serverless_examples_are_a40_only() -> None:
    pod = json.loads((PROJECT_ROOT / "deploy" / "runpod-pod.example.json").read_text())
    endpoint = json.loads((PROJECT_ROOT / "deploy" / "runpod-endpoint.example.json").read_text())

    assert pod["compute"]["preferred_gpu"] == "NVIDIA A40"
    assert pod["compute"]["gpu_vram_minimum_gb"] == 48
    assert pod["environment"]["FW_MVP_STACK_ID"] == "firewarning-mvp-a40-v1"
    assert pod["environment"]["FW_QWEN_GPU_MEMORY_GIB"] == "44"
    assert endpoint["allowed_gpu"] == "NVIDIA A40"
    assert endpoint["gpu_vram_minimum_gb"] == 48
    assert endpoint["environment"]["FW_MVP_STACK_ID"] == "firewarning-mvp-a40-v1"
    for environment in (pod["environment"], endpoint["environment"]):
        assert environment["FW_ENABLE_FIRE_DETECTOR_ENSEMBLE"] == "true"
        assert environment["FW_ENABLE_CONSENSUS_JUDGE"] == "true"
        assert "FW_RTDETR_CHECKPOINT_PATH" not in environment
        assert "FW_RTDETR_CHECKPOINT_SHA256" not in environment


def test_container_enables_the_pinned_public_detector_ensemble() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FW_ENABLE_FIRE_DETECTOR_ENSEMBLE=true" in dockerfile
    assert "FW_ENABLE_CONSENSUS_JUDGE=true" in dockerfile
    assert "FW_RTDETR_CHECKPOINT_PATH" not in dockerfile
