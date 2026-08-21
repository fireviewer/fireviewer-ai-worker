"""Part.3 coarse localization primitives that do not depend on the map builder."""

from firewarning_worker.mvp.localization.event_localizer import (
    EventLocalizationConfig,
    LocalEvidenceImageLoader,
    MegaLocFaissEventLocalizer,
    abstain_for_missing_reference_coverage,
)
from firewarning_worker.mvp.localization.evidence_fusion import (
    DeterministicEvidenceFusion,
    FusionConfig,
    FusionWeights,
    haversine_m,
)
from firewarning_worker.mvp.localization.local_megaloc_bundle import (
    LocalMegaLocBundleManifest,
    LocalMegaLocModelLoader,
    inspect_local_megaloc_bundle,
)
from firewarning_worker.mvp.localization.panoramax_cache import (
    CachedPanoramaxImageLoader,
    PanoramaxCacheManifest,
    materialize_panoramax_cache,
)
from firewarning_worker.mvp.localization.regional_index import (
    CallablePanoramaxImageLoader,
    PanoramaxRegionalIndexBuilder,
    RegionalIndexConfig,
)
from firewarning_worker.mvp.localization.retrieval import MegaLocFaissRetriever, RetrievalConfig

__all__ = [
    "CachedPanoramaxImageLoader",
    "CallablePanoramaxImageLoader",
    "DeterministicEvidenceFusion",
    "EventLocalizationConfig",
    "FusionConfig",
    "FusionWeights",
    "LocalEvidenceImageLoader",
    "LocalMegaLocBundleManifest",
    "LocalMegaLocModelLoader",
    "MegaLocFaissEventLocalizer",
    "MegaLocFaissRetriever",
    "PanoramaxCacheManifest",
    "PanoramaxRegionalIndexBuilder",
    "RegionalIndexConfig",
    "RetrievalConfig",
    "abstain_for_missing_reference_coverage",
    "haversine_m",
    "inspect_local_megaloc_bundle",
    "materialize_panoramax_cache",
]
