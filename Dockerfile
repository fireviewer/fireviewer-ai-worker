FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime@sha256:417bd75df6365104c283ea4c1651fb3530d9eb5a4c2fafa51943cff2a94e6385 AS sandbox-builder

RUN apt-get update \
    && apt-get install --yes --no-install-recommends gcc libc6-dev linux-libc-dev \
    && rm -rf /var/lib/apt/lists/*
COPY sandbox/research_sandbox.c /tmp/research_sandbox.c
RUN gcc -O2 -Wall -Wextra -Werror /tmp/research_sandbox.c -o /fw-research-sandbox

FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime@sha256:417bd75df6365104c283ea4c1651fb3530d9eb5a4c2fafa51943cff2a94e6385

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HOME=/runpod-volume/huggingface-cache \
    FW_HF_CACHE_ROOT=/runpod-volume/huggingface-cache/hub \
    FW_ROMA_ROOT=/runpod-volume/firewarning-roma \
    FW_AUTO_PREFETCH_MODELS=true \
    HF_ENABLE_PARALLEL_LOADING=true \
    HF_PARALLEL_LOADING_WORKERS=4 \
    FW_ENABLE_TRANSFORMERS_RUNTIME=true \
    FW_ENABLE_SOURCE_RESEARCH=true \
    FW_ENABLE_RTDETR_BASELINE=true \
    FW_MVP_STACK_ID=firewarning-mvp-a40-v1 \
    FW_QWEN_GPU_MEMORY_GIB=44 \
    FW_QWEN_CPU_MEMORY_GIB=48 \
    FW_QWEN_VL_MAX_PIXELS=1048576 \
    FW_QWEN_VL_TOTAL_PIXELS=4194304 \
    FW_MAX_MEDIA_CACHE_BYTES=4294967296 \
    FW_RESEARCH_SANDBOX_LAUNCHER=/usr/local/bin/fw-research-sandbox \
    FW_ATTENTION_IMPLEMENTATION=flash_attention_2

COPY --from=sandbox-builder /fw-research-sandbox /usr/local/bin/fw-research-sandbox

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/firewarning-worker
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir '.[runtime,roma-registration]' \
    && python -m pip install --no-cache-dir --no-deps torchvision==0.23.0 \
    && rm -rf build src

# Install only the audited inference source at its immutable commit.  The
# checkpoint and DINOv2 backbone are deliberately absent from this public
# image and must be provisioned into FW_ROMA_ROOT before a GPU pod starts.
ARG ROMA_SOURCE_URL=https://codeload.github.com/Xecades/AerialExtreMatch/tar.gz/048ab96f84430f3e0f1144f05c94fe1e1f0bca8a
ARG ROMA_SOURCE_SHA256=c95644abd917c62d7bbcad4ff057201aecf61daab282520603c4db606ecac5b4
RUN python -c "from urllib.request import urlretrieve; urlretrieve('${ROMA_SOURCE_URL}', '/tmp/aerialextrematch-roma.tar.gz')" \
    && echo "${ROMA_SOURCE_SHA256}  /tmp/aerialextrematch-roma.tar.gz" | sha256sum --check --strict \
    && python -m pip install --no-cache-dir --no-deps /tmp/aerialextrematch-roma.tar.gz \
    && rm /tmp/aerialextrematch-roma.tar.gz \
    && python -c "import cv2, kornia, romatch, torchvision; from firewarning_worker.roma_registration import ROMA_SOURCE_REVISION; assert ROMA_SOURCE_REVISION == '048ab96f84430f3e0f1144f05c94fe1e1f0bca8a'"

# Official upstream wheel, pinned by version and content digest. Downloading,
# verifying, installing and deleting it in one layer avoids retaining the
# 256 MiB compressed wheel in the public image.
ARG FLASH_ATTN_WHEEL_URL=https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3/flash_attn-2.8.3%2Bcu12torch2.8cxx11abiTRUE-cp311-cp311-linux_x86_64.whl
ARG FLASH_ATTN_WHEEL_SHA256=3d41b2fc55753faa7f45d6568ea73a96b96afb48b82994ab9b49bcbcb6c87588
RUN python -c "from urllib.request import urlretrieve; urlretrieve('${FLASH_ATTN_WHEEL_URL}', '/tmp/flash_attn-2.8.3+cu12torch2.8cxx11abiTRUE-cp311-cp311-linux_x86_64.whl')" \
    && echo "${FLASH_ATTN_WHEEL_SHA256}  /tmp/flash_attn-2.8.3+cu12torch2.8cxx11abiTRUE-cp311-cp311-linux_x86_64.whl" | sha256sum --check --strict \
    && python -m pip install --no-cache-dir --no-deps \
        /tmp/flash_attn-2.8.3+cu12torch2.8cxx11abiTRUE-cp311-cp311-linux_x86_64.whl \
    && rm /tmp/flash_attn-2.8.3+cu12torch2.8cxx11abiTRUE-cp311-cp311-linux_x86_64.whl \
    && python -c "import flash_attn; assert flash_attn.__version__ == '2.8.3'"

COPY scripts/prefetch_models.py ./scripts/prefetch_models.py

RUN groupadd --gid 10000 firewarning \
    && groupadd --gid 10001 firewarning-model \
    && useradd --create-home --uid 10001 --groups firewarning,firewarning-model worker \
    && useradd --create-home --uid 10002 --groups firewarning broker \
    && useradd --create-home --uid 10003 --groups firewarning,firewarning-model researcher \
    && chmod 0755 /usr/local/bin/fw-research-sandbox
# The bootstrap needs to initialize a fresh root-owned RunPod mount. It drops
# to this unprivileged account before exec'ing the inference handler.
ENV FW_RUNTIME_USER=worker
USER root

EXPOSE 8000

ENTRYPOINT ["python", "-m", "firewarning_worker.bootstrap"]
