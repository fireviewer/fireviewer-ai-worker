# FireViewer AI Worker

The FireViewer AI Worker acquires and transforms private event evidence. It
connects bounded source research, image and video processing, deterministic
geographic hypotheses, optional managed providers, event memory, and structured
point assessment.

> This component does not issue emergency alerts, publish incidents, define
> official coordinates, or predict fire spread. Its outputs are versioned
> proposals that can be rejected or held for review.

## Role in FireViewer

```text
source pages / authorised images / video / satellite references
                              |
                              v
          evidence acquisition and visual observations
                              |
                              v
             deterministic geographic hypotheses
                              |
                              v
             EventEvidence and event-history retrieval
                              |
                              v
             compact PointEvidenceBundle per point
                              |
                              v
              managed multimodal PointAssessment
                              |
                              v
                    guarded backend receipt
                              |
                              v
         deterministic backend Part.4 perimeter candidate
```

The worker follows a provider architecture: external search, multimodal
extraction, visual detection, terrain, maps, satellite processing, and final
supervision can be replaced independently as long as they preserve the same
strict contracts and failure semantics.

## Implemented areas

- strict `EventEvidence`, geographic-hypothesis, point-bundle, and
  point-assessment contracts;
- bounded HTTP acquisition, domain policies, automatic research planning,
  media-candidate collection, deduplication, and source tickets;
- in-memory multimodal extraction from a page and a bounded public-image set;
- durable CPU video-keyframe extraction followed by the replaceable CPU YOLO
  smoke detector;
- upload-location, camera, map, terrain, visibility, uncertainty, and
  history-aware geographic hypothesis services;
- durable read/write adapters for backend evidence, derived keyframes,
  geographic hypotheses, and terrain references;
- provider boundaries for optional cross-view and satellite acceleration;
- bounded CLMS, Sentinel-2 optical-change, Sentinel-1 radar-change, and
  Sentinel-3 FRP observation paths, with immutable source receipts, valid
  coverage, probability buckets, explicit credentials, invocation, and
  paid-provider gates;
- spatio-temporal event retrieval and compact evidence-bundle assembly;
- managed and simulated multimodal supervisors with strict JSON output and
  bounded managed-model invocation counts;
- calibrated publication policy, contradiction handling, competing-point JSON,
  and explicit abstention;
- CPU and optional GPU container entry points for independently scalable stages.

Presence in this repository does not mean that every provider is configured,
funded, deployed, or accepted on real data. The complete acquisition-to-review
flow remains an integration milestone.

## Geographic safety boundary

YOLO and other detectors supply image-space boxes, classes, and scores only.
They never produce authoritative coordinates. Candidate GPS points come from a
separate deterministic stage using the upload position, declared accuracy,
orientation and field of view when available, terrain, map and satellite
references, and earlier reviewed fire states.

The final vision-language supervisor judges a supplied candidate. It may
`accept`, `reject`, or `abstain`; it may not mutate the source point. A proposed
correction is a competing JSON object with its own evidence references.

Automatic-publication eligibility requires calibrated confidence strictly
above 0.85, an accepted managed-provider result, and no hard contradiction or
missing required evidence. Simulated outputs are always held for review.

The worker never draws the final perimeter. It supplies dated, referenced
spatial observations to backend Part.4, where an allowlisted, versioned profile
drives deterministic probability-grid reconstruction. Pixels and frames from
one product lineage remain spatially visible but cannot masquerade as independent
sources. Media are evidence inputs, not the pipeline deliverable.

## Data boundary

The acquisition layer retains evidence tickets, source references, hashes,
derived claims, outcomes, and failure information. It is not intended to retain
complete scraped articles, public-media binaries, or full transcripts. Raw
third-party content is discarded after bounded in-memory processing unless a
separate right and retention rule explicitly apply.

No private incident evidence, model weights, checkpoints, provider secrets, or
generated inference payloads belong in Git.

Large inactive artifacts are inventoried with `fireviewer-artifact-audit` and
classified as active, remotely available, legacy, rebuildable, unused dataset,
or unknown. Redistributable legacy checkpoints live in a private common Hugging
Face archive; third-party weights remain pinned to their upstream provider.
Inactive datasets are likewise stored or referenced by immutable Hub revision.
Job caches use at most 20 GiB or ten percent of free space, whichever is lower,
and are removed after the remote revision, file sizes, and one representative
read have been confirmed. Production never consumes the common legacy archive
directly; a reactivated model must first be promoted to a dedicated repository.

## Development

Python 3.11–3.13 is required.

```bash
python -m pip install -e ".[dev]"
ruff check src tests training
ruff format --check src tests training
mypy src
pytest -q
```

Optional extras in `pyproject.toml` install only the dependencies required for
a selected stage. CPU, container, cloud-provider, GPU, and real-data acceptance
remain separate gates; local unit tests do not prove them.

The Eve point-supervisor harness has its own Node workspace:

```bash
cd eve-point-supervisor
npm ci
npm run build
```

## Contracts and project documentation

- [Source acquisition method](docs/SOURCE_ACQUISITION_METHOD.md) defines the
  incident/day acquisition loop, media and satellite handling, coverage gates,
  retention boundary, and evaluation isolation.
- [`contracts/point-supervisor/v1`](contracts/point-supervisor/v1/README.md)
  documents the public point-supervision schemas.
- [`contracts/geographic-hypotheses/v1`](contracts/geographic-hypotheses/v1/geographic-hypotheses.schema.json)
  contains the geographic-hypothesis schema.
- [Canonical FireViewer documentation](https://github.com/fireviewer/Fireviewer_doc)
  explains architecture, data governance, safety, and current maturity.

Code is licensed under AGPL-3.0-or-later. Original documentation is available
under CC BY 4.0. Models, datasets, services, and upstream assets retain their
own terms. See [SECURITY.md](SECURITY.md) for responsible disclosure.
