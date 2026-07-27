from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_public_docker_context_excludes_private_payloads() -> None:
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")
    for private_pattern in (".env", ".secrets", "checkpoints", "data", "*.safetensors"):
        assert private_pattern in dockerignore


def test_runpod_endpoint_requires_flash_attention_2() -> None:
    endpoint = json.loads(
        (PROJECT_ROOT / "deploy" / "runpod-endpoint.example.json").read_text(encoding="utf-8")
    )
    assert endpoint["environment"]["FW_ATTENTION_IMPLEMENTATION"] == "flash_attention_2"
    assert endpoint["environment"]["FW_ROMA_ROOT"] == "/runpod-volume/firewarning-roma"


def test_public_image_provisions_models_only_on_an_external_volume() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FW_ROMA_ROOT=/runpod-volume/firewarning-roma" in dockerfile
    assert "FW_AUTO_PREFETCH_MODELS=true" in dockerfile
    assert "HF_ENABLE_PARALLEL_LOADING=true" in dockerfile
    assert "HF_PARALLEL_LOADING_WORKERS=4" in dockerfile
    assert "FW_MAX_MEDIA_CACHE_BYTES=4294967296" in dockerfile
    assert "COPY scripts/prefetch_models.py" in dockerfile
    assert "ENV FW_RUNTIME_USER=worker" in dockerfile
    assert "USER root" in dockerfile
    assert 'ENTRYPOINT ["python", "-m", "firewarning_worker.bootstrap"]' in dockerfile
    assert "roma_extre.pth" not in dockerfile
    assert "dinov2_vitl14_pretrain.pth" not in dockerfile
    assert "COPY data" not in dockerfile
    assert "COPY datasets" not in dockerfile


def test_public_image_runs_research_behind_dedicated_users_and_seccomp() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    sandbox = (PROJECT_ROOT / "sandbox" / "research_sandbox.c").read_text(encoding="utf-8")

    assert "useradd --create-home --uid 10002 --groups firewarning broker" in dockerfile
    assert "useradd --create-home --uid 10003" in dockerfile
    assert "FW_ENABLE_SOURCE_RESEARCH=true" in dockerfile
    assert "fw-research-sandbox" in dockerfile
    assert "PR_SET_NO_NEW_PRIVS" in sandbox
    assert "PR_SET_SECCOMP" in sandbox
    assert "AF_INET" in sandbox
    assert "AF_INET6" in sandbox
    assert "AF_PACKET" in sandbox


def test_persistent_pod_enables_research_without_embedding_weights_or_secrets() -> None:
    pod = json.loads(
        (PROJECT_ROOT / "deploy" / "runpod-pod.example.json").read_text(encoding="utf-8")
    )

    assert pod["environment"]["FW_ENABLE_SOURCE_RESEARCH"] == "true"
    assert pod["environment"]["FW_ATTENTION_IMPLEMENTATION"] == "flash_attention_2"
    assert pod["environment"]["HF_ENABLE_PARALLEL_LOADING"] == "true"
    assert pod["environment"]["HF_PARALLEL_LOADING_WORKERS"] == "4"
    assert int(pod["environment"]["FW_MAX_MEDIA_CACHE_BYTES"]) == 4 * 1024**3
    assert pod["compute"]["gpu_vram_minimum_gb"] >= 20
    assert pod["compute"]["cpu_ram_minimum_gb"] >= 64
    assert int(pod["environment"]["FW_QWEN_GPU_MEMORY_GIB"]) < pod["compute"]["gpu_vram_minimum_gb"]
    assert pod["backend"]["FV_AGENT_RESEARCH_ENABLED"] == "true"
    assert pod["backend"]["FV_AGENT_RESEARCH_SOURCE_REGISTRY_VERSION"].startswith(
        "firewarning-fr-sources-"
    )
    assert any("seccomp" in constraint for constraint in pod["constraints"])


def test_git_repository_excludes_model_weights_and_datasets() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    for private_pattern in (
        "**/dataset/",
        "**/datasets/",
        "**/checkpoints/",
        "**/weights/",
        "**/huggingface-cache/",
        "*.pth",
        "*.safetensors",
    ):
        assert private_pattern in gitignore
