from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from PIL import Image

from firewarning_worker.mvp.benchmarks.corpus import Summer2026Corpus
from firewarning_worker.mvp.contracts import EvidenceMedia
from firewarning_worker.mvp.localization import LocalEvidenceImageLoader
from firewarning_worker.mvp.orchestration import prepare_corpus_event

CORPUS_PATH = Path(
    "benchmarks/mvp-event-localization/corpus/france-summer-2026-media-ready.v1.json"
)


def test_all_summer_cases_convert_to_runtime_inputs_with_twenty_real_media() -> None:
    corpus = Summer2026Corpus.model_validate_json(CORPUS_PATH.read_text(encoding="utf-8"))

    runtime_inputs = tuple(prepare_corpus_event(case) for case in corpus.cases)

    assert len(runtime_inputs) == 9
    assert sum(len(item.evidence.media) for item in runtime_inputs) == 180
    assert all(len(item.evidence.media) == 20 for item in runtime_inputs)
    assert all(
        len({media.media_group_id for media in item.evidence.media}) <= len(item.evidence.sources)
        for item in runtime_inputs
    )


def test_materialized_media_loader_verifies_a_synthetic_payload(tmp_path: Path) -> None:
    image_path = tmp_path / "example.png"
    Image.new("RGB", (8, 6), color=(20, 40, 60)).save(image_path)
    media = EvidenceMedia(
        media_id="MEDIA-SYNTHETIC-1",
        source_id="SOURCE-SYNTHETIC-1",
        media_group_id="GROUP-SYNTHETIC-1",
        origin_id="ORIGIN-SYNTHETIC-1",
        kind="photo",
        sha256=sha256(image_path.read_bytes()).hexdigest(),
    )
    loader = LocalEvidenceImageLoader(
        root=tmp_path,
        relative_paths_by_media_id={media.media_id: image_path.name},
    )

    image = loader.load(media)

    assert isinstance(image, Image.Image)
    assert image.mode == "RGB"
    assert image.size == (8, 6)
