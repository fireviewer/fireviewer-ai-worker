from __future__ import annotations

from pathlib import Path

from PIL import Image

from firewarning_worker.mvp.benchmarks.corpus import Summer2026Corpus
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


def test_materialized_media_loader_verifies_a_real_reviewed_payload() -> None:
    corpus = Summer2026Corpus.model_validate_json(CORPUS_PATH.read_text(encoding="utf-8"))
    runtime_input = prepare_corpus_event(corpus.cases[0])
    loader = LocalEvidenceImageLoader(
        root=Path.cwd(),
        relative_paths_by_media_id=runtime_input.relative_paths_by_media_id,
    )

    image = loader.load(runtime_input.evidence.media[0])

    assert isinstance(image, Image.Image)
    assert image.mode == "RGB"
    assert image.width > 0 and image.height > 0
