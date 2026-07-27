from __future__ import annotations

from hashlib import sha256

import pytest

from firewarning_worker.model_registry import (
    RTDETR_BASELINE,
    ModelSpec,
    RegistryError,
    build_registry,
    resolve_cached_snapshot,
)


def test_floating_hugging_face_revision_is_forbidden() -> None:
    with pytest.raises(RegistryError, match="immutable"):
        ModelSpec(role="asr", model_id="org/model", revision="main").validate()


def test_cache_resolution_requires_the_exact_commit(tmp_path) -> None:
    spec = ModelSpec(role="asr", model_id="org/model", revision="a" * 40)
    snapshot = tmp_path / "models--org--model" / "snapshots" / ("a" * 40)
    snapshot.mkdir(parents=True)
    assert resolve_cached_snapshot(spec, tmp_path) == snapshot
    with pytest.raises(RegistryError, match="absent"):
        resolve_cached_snapshot(
            ModelSpec(role="asr", model_id="org/model", revision="b" * 40), tmp_path
        )


def test_private_detector_digest_is_recalculated(monkeypatch, tmp_path) -> None:
    checkpoint = tmp_path / "rtdetr"
    checkpoint.mkdir()
    weights = checkpoint / "model.safetensors"
    weights.write_bytes(b"verified checkpoint")
    digest = sha256(weights.read_bytes()).hexdigest()
    monkeypatch.setenv("FW_RTDETR_CHECKPOINT_PATH", str(checkpoint))
    monkeypatch.setenv("FW_RTDETR_CHECKPOINT_SHA256", digest)
    assert build_registry()["fire_detection"].revision == f"sha256:{digest}"
    monkeypatch.setenv("FW_RTDETR_CHECKPOINT_SHA256", "0" * 64)
    with pytest.raises(RegistryError, match="does not match"):
        build_registry()


def test_public_detector_baseline_is_explicitly_toggleable(monkeypatch) -> None:
    monkeypatch.delenv("FW_RTDETR_CHECKPOINT_PATH", raising=False)
    monkeypatch.delenv("FW_RTDETR_CHECKPOINT_SHA256", raising=False)
    monkeypatch.setenv("FW_ENABLE_RTDETR_BASELINE", "false")

    assert "fire_detection" not in build_registry()

    monkeypatch.setenv("FW_ENABLE_RTDETR_BASELINE", "true")
    detector = build_registry()["fire_detection"]
    assert detector == RTDETR_BASELINE
    assert detector.model_id == "PekingU/rtdetr_v2_r50vd"
    assert detector.revision == "282494075698cab9faa1096ae26856890030c817"


def test_runtime_models_use_full_strength_pinned_variants(monkeypatch) -> None:
    monkeypatch.setenv("FW_ENABLE_RTDETR_BASELINE", "false")
    registry = build_registry()

    assert registry["source_research"].model_id == "Qwen/Qwen3-14B"
    assert registry["source_research"].revision == ("40c069824f4251a91eefaf281ebe4c544efd3e18")
    assert registry["multimodal_extraction"].model_id == "Qwen/Qwen3.5-9B"
    assert registry["multimodal_extraction"].revision == (
        "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
    )
    assert registry["asr"].model_id == "openai/whisper-large-v3"


def test_private_detector_overrides_enabled_public_baseline(monkeypatch, tmp_path) -> None:
    checkpoint = tmp_path / "rtdetr-private"
    checkpoint.mkdir()
    weights = checkpoint / "model.safetensors"
    weights.write_bytes(b"private FireWarning checkpoint")
    digest = sha256(weights.read_bytes()).hexdigest()
    monkeypatch.setenv("FW_ENABLE_RTDETR_BASELINE", "true")
    monkeypatch.setenv("FW_RTDETR_CHECKPOINT_PATH", str(checkpoint))
    monkeypatch.setenv("FW_RTDETR_CHECKPOINT_SHA256", digest)

    detector = build_registry()["fire_detection"]

    assert detector.source == "local"
    assert detector.revision == f"sha256:{digest}"
