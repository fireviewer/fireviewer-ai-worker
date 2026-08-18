# FireViewer AI Worker

**Private multimodal analysis, visual anchoring, localisation attempts and explicit abstention for FireViewer evidence.**

This repository contains the AI-analysis runtime, contracts, orchestration helpers and evaluation tooling used by FireViewer. It does not contain production media, private incident evidence, model weights, checkpoints, secrets or incident-specific inference outputs.

The canonical project architecture is maintained in [`fireviewer/Fireviewer_doc`](https://github.com/fireviewer/Fireviewer_doc).

> The worker produces proposals and derived evidence. It does not confirm a wildfire, publish an incident, invent an authoritative coordinate or forecast propagation.

## Role in FireViewer

```text
private event/evidence bundle
        ↓
media + context analysis
        ↓
visual anchors / structured facts
        ↓
spatial localisation attempt
        ↓
geometry + uncertainty
        OR
explicit abstention
        ↓
backend + human review
```

The worker is one analysis layer inside a broader provenance/replay system. A model result is never the canonical incident state by itself.

## Event-oriented input

The preferred input is a private `event-2.0` bundle rather than an isolated image.

It can include:

- event candidate identity;
- private viewpoint when authorised;
- observation time/interval;
- message/text;
- authorised media;
- evidence provenance;
- external observations already collected by the backend.

The viewpoint represents the observer/camera and is never automatically converted into a fire location.

## Output

`event-result-2.0` keeps separate fields for:

- capture/view profile;
- visual anchors;
- structured evidence/facts;
- localisation attempts;
- spatial evidence and uncertainty;
- contradictions;
- draft activity proposals;
- abstention/failure reasons;
- model/tool revision information.

Human review remains the publication boundary.

## Abstention is a first-class result

FireViewer deliberately allows the worker to stop when evidence is insufficient.

Examples include:

```text
insufficient_visual_anchor
ambiguous_anchor
no_visible_ground_origin
insufficient_geometry
unstable_camera_pose
invalid_raycast
uncertainty_above_limit
```

A visually plausible guess is not preferred over a defensible abstention.

## Model roles

FireViewer can combine several specialised model/tool families. Their exact promotion status belongs in the canonical [Status Matrix](https://github.com/fireviewer/Fireviewer_doc/blob/main/docs/STATUS_MATRIX.md), not in marketing copy.

Current/experimental roles include:

- image detection;
- video triage;
- visual pointing/anchoring;
- OCR/speech extraction where applicable;
- structured fact extraction;
- spatial matching and registration;
- deterministic pose/raycast stages;
- segmentation/pointing challengers;
- annotation tooling.

A component may be integrated, benchmark-only, shadow, blocked or historical.

## Spatial localisation boundary

A language model is not authorised to invent latitude/longitude.

The target spatial path is evidence/geometric:

```text
FireViewer map package
→ local references / retrieval
→ geometric filters
→ dense matching
→ 2D–3D correspondences
→ robust camera pose
→ terrain raycast
→ uncertainty propagation
```

The worker can structure the evidence around this process and report why it failed, but it cannot replace the geometric chain with generated coordinates.

## Provenance and replay

Every accepted analysis should preserve enough information to identify:

- parent evidence;
- model identifier and revision;
- inference/processing profile;
- contract revision;
- producing stage;
- parameters required for replay where applicable;
- output hash/reference;
- abstention or failure state.

A future replay can therefore compare a newer model against archived evidence without rewriting the historical FireViewer result.

See [Provenance and Reproducibility](https://github.com/fireviewer/Fireviewer_doc/blob/main/docs/PROVENANCE_AND_REPRODUCIBILITY.md) and [Replay and Post-Event Studies](https://github.com/fireviewer/Fireviewer_doc/blob/main/docs/REPLAY_AND_POST_EVENT_STUDIES.md).

## Documentation in this repository

- [`docs/PIPELINE_V2.md`](docs/PIPELINE_V2.md) — stage graph and promotion rules;
- [`docs/SPATIAL_REGISTRATION.md`](docs/SPATIAL_REGISTRATION.md) — registration, raycast and spatial abstention;
- [`docs/REPLAY_AND_PROVENANCE.md`](docs/REPLAY_AND_PROVENANCE.md) — worker-level replay requirements;
- [`docs/MODEL_REGISTRY.md`](docs/MODEL_REGISTRY.md) — model roles and revisions;
- [`docs/BENCHMARK_GATES.md`](docs/BENCHMARK_GATES.md) — evaluation gates;
- [`docs/BACKEND_INTEGRATION.md`](docs/BACKEND_INTEGRATION.md) — trust boundary with the backend.

Cross-project meaning, safety, architecture and status remain canonical in `Fireviewer_doc`.

## Installation and checks

```bash
python -m pip install -e ".[dev]"
ruff check src tests scripts training tools
ruff format --check src tests scripts training tools
mypy src
pytest -q
docker build -t fireviewer-ai-worker:local .
```

Local tests use controlled/synthetic fixtures. They do not prove CUDA availability, current model weights, deployed provider behaviour or field accuracy.

## Runtime configuration

Secrets and model/data roots are supplied at runtime.

The repository must not contain:

- model-provider tokens;
- private evidence URLs;
- Hugging Face tokens;
- production incident bundles;
- model caches/weights;
- generated inference outputs.

The contract producer lives under `contracts/agent-worker`. Consumers should lock compatible contract revisions rather than relying on undocumented output shape.

## Benchmarks before promotion

Long training or challenger promotion should follow a fixed event-level benchmark.

The evaluation should distinguish:

- localisation error on valid targets;
- accepted-localisation failure severity;
- abstention behaviour;
- calibration/uncertainty where defensible;
- incident/source leakage;
- hard negatives and ambiguous views;
- runtime cost/latency when measured reproducibly.

No model is promoted on one headline metric.

## Data and licences

Training/evaluation scripts accept explicit external data roots. Data and generated outputs stay outside the Git checkout.

The code is licensed under AGPL-3.0-or-later and the repository documentation under CC BY 4.0. External models and datasets retain their own licences and usage conditions.

## Support and collaboration

This workstream benefits from GPU credits, held-out evaluation cases, computer-vision/geospatial expertise and independent benchmark review.

See the FireViewer [Funding Brief](https://github.com/fireviewer/Fireviewer_doc/blob/main/docs/FUNDING_BRIEF.md) and [Support & Partnerships](https://github.com/fireviewer/Fireviewer_doc/blob/main/docs/SUPPORT_AND_PARTNERSHIPS.md).

## Contact

FireViewer is maintained by **Unicorn Who Dev**.

Research collaboration, infrastructure support, provenance, security and data-removal requests: **unicornwhodev@gmail.com**.
