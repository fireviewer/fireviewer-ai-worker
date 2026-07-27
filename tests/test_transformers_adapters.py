from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image

from firewarning_worker.contracts import BatchItem
from firewarning_worker.model_registry import ModelSpec
from firewarning_worker.transformers_adapters import (
    WhisperAdapter,
    _bounded_image,
    _qwen_memory_limits,
)


def test_qwen_memory_limits_reserve_vram_for_activations(monkeypatch) -> None:
    monkeypatch.setenv("FW_QWEN_GPU_MEMORY_GIB", "17")
    monkeypatch.setenv("FW_QWEN_CPU_MEMORY_GIB", "48")

    assert _qwen_memory_limits() == {0: "17GiB", "cpu": "48GiB"}


def test_qwen_image_is_resized_to_the_pixel_budget() -> None:
    image = Image.new("RGB", (2_000, 1_000))

    resized = _bounded_image(image, max_pixels=500_000)

    assert resized.size[0] * resized.size[1] <= 500_000
    assert resized.size[0] == 2 * resized.size[1]
    resized.close()


class FakeWhisperFetcher:
    def __init__(self, audio_path: Path) -> None:
        self.audio_path = audio_path

    @contextmanager
    def download(self, _url: str):
        yield self.audio_path


def test_whisper_pipeline_is_built_once_per_loaded_adapter(monkeypatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    pipeline_calls: list[dict[str, Any]] = []
    inference_calls: list[str] = []

    class FakeModel:
        dtype = "float16"

        def to(self, _device: str):
            return self

    processor = SimpleNamespace(tokenizer=object(), feature_extractor=object())

    def build_pipeline(_task: str, **kwargs: Any):
        pipeline_calls.append(kwargs)

        def infer(path: str, **_options: Any):
            inference_calls.append(path)
            return {"language": "fr", "chunks": []}

        return infer

    transformers = SimpleNamespace(
        AutoProcessor=SimpleNamespace(from_pretrained=lambda *_args, **_kwargs: processor),
        AutoModelForSpeechSeq2Seq=SimpleNamespace(
            from_pretrained=lambda *_args, **_kwargs: FakeModel()
        ),
        pipeline=build_pipeline,
    )
    torch = SimpleNamespace(float16="float16")
    monkeypatch.setattr(
        "firewarning_worker.transformers_adapters._torch_runtime",
        lambda: (torch, transformers),
    )
    monkeypatch.setattr(
        "firewarning_worker.transformers_adapters.resolve_cached_snapshot",
        lambda _spec, _cache_root: tmp_path,
    )
    adapter = WhisperAdapter(
        ModelSpec(
            role="asr",
            model_id="openai/whisper-large-v3",
            revision="0" * 40,
        ),
        cache_root=tmp_path,
        fetcher=FakeWhisperFetcher(audio_path),  # type: ignore[arg-type]
    )
    item = BatchItem.model_validate(
        {
            "input_id": "AUDIO-1",
            "media_type": "audio",
            "audio_url": "https://media.internal/audio.wav",
        }
    )

    adapter.load()
    adapter.infer((item,), {})
    adapter.infer((item,), {})

    assert len(pipeline_calls) == 1
    assert inference_calls == [str(audio_path), str(audio_path)]

    adapter.unload()

    assert adapter.pipeline is None
    assert adapter.model is None
    assert adapter.processor is None
