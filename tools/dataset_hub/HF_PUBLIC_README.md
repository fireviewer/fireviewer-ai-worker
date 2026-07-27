---
pretty_name: FireWarning Training Bundles v1
license: other
language:
- en
- fr
size_categories:
- 100G<n<1T
task_categories:
- object-detection
- image-segmentation
- text-generation
- visual-question-answering
tags:
- wildfire
- fire-detection
- burned-area
- cross-view-localization
- geospatial
---

# FireWarning Training Bundles v1

Fifteen self-contained, versioned ZIP64 packages prepared for the FireWarning training pipeline.
Every training objective has exactly one ZIP. Each ZIP contains its source payloads,
manifests, attribution and license metadata, entry-point contract, and a complete SHA-256
inventory under a single root directory.

> **Contrats à ne pas exécuter tels quels.** Les ZIP publics
> `fire-pointing-lora-v1.zip` et `cross-view-localization-v1.zip` conservent leur ancien
> `TRAIN_BUNDLE.json`. Les données et
> empreintes restent valides, mais les entrypoints doivent être remplacés par la révision
> `mvp-a40-v2` décrite dans `PUBLIC_BUNDLE_CONTRACT_REPAIRS.md`. Aucune reconstruction ni
> republication de ces deux ZIP n'est effectuée dans cette passe.

| Training objective | ZIP | Size (bytes) | SHA-256 | State |
|---|---|---:|---|---|
| Fire/smoke media filter | `media-filter-fire-smoke-v1.zip` | 32,772,718,037 | `ed6ee4cf71a2538cfce7b95e6e548528d94b4cea095c8d03ccfc4c0e5ba4c8ae` | Training-ready |
| Burned-area segmentation | `burned-area-segmentation-v1.zip` | 27,926,097,197 | `85c2f17248528ebbd5aa8395e72435ba5a12626bb5a53f5730109b11ea5dde36` | Dataset-ready; training blocked until independent geographic test |
| Cross-view localization | `cross-view-localization-v1.zip` | 15,895,751,194 | `5f5e14083da209bd978117e2c7470f8f63decdb4ba3223914da7e7164aa64f5f` | Data valid; DINOv2 entrypoint obsolete, rebuild required |
| Fire pointing LoRA | `fire-pointing-lora-v1.zip` | 32,589,764,131 | `a43cda497078b89960c300fce26280171441cf6111c208f96adfcfdecdc9762b` | Data valid; Qwen entrypoints obsolete, rebuild required |
| Cross-view registration | `cross-view-registration-v1.zip` | 2,299,599,606 | `a7e7d9205c34f96cf1843a7b7a9455e81a704c2926b9ba648bb00ecbddbc2f1e` | Dataset-ready; RoMa quality gate, double-validated test, and fine-tuning contract pending |
| Fire/smoke/normal media triage | `media-triage-fire-smoke-v1.zip` | 31,688,094,244 | `0ce5a30979007468efa8dd2f2ec5b20547943e080a6ed36318297023456ece34` | Dataset-ready; classifier trainer and independent critical test pending |
| Orchestrator gates SFT | `orchestrator-gates-sft-v1.zip` | 17,444 | `3ca4813cae6f04b806fce16be7a08a6854409dcd96df166d62a346e6d9a809ff` | Dataset-ready; SFT trainer and independent human validation pending |
| Fire progression/front inference | `fire-progression-front-inference-v1.zip` | 6,493,320 | `0bb682ee726d3ec62054e5c44b7dc84e0a0658e5e8ca5a1286662056020b7f11` | Dataset-ready; observed active-front labels and independent geographic test pending |
| Daily wildfire fact synthesis | `daily-wildfire-fact-synthesis-v1.zip` | 222,162 | `9e4c7dde666b964a3f38ae64c50383cd7faff7fbdab9d32a42b6ccca398fe332` | Dataset-ready; raw source documents and France validation pending |
| Structured wildfire situation/resources | `wildfire-situation-resources-structured-v1.zip` | 8,696,884 | `fc8bd5f419183b1ba603aab2117be842b75ad9acd46f9ba10eb2fff73e6ceb02` | Dataset-ready; France validation and stable incident identifiers pending |
| Engaged-assets object detection | `engaged-assets-object-detection-v1.zip` | 1,193,478,095 | `9a8e746f77ed88b7a8b3fa29ea13448f12ee9e8cdc6841ddfd8175950c079178` | Dataset-ready; fire-engine and operational-role labels pending |
| Camera depth and pose prior | `camera-depth-pose-prior-v1.zip` | 39,593,395,922 | `4f9574b2920126e7f34d62759ff0192c53062bc337e206309106beb0f670c280` | Dataset-ready; synthetic-only, real rural critical test pending |
| Outdoor metric depth | `outdoor-metric-depth-v1.zip` | 132,759,914,158 | `b9aa757c2e52007a3db40fc3c7f0878fb7dd391464832142e8d9b104cbb22bf2` | Training-ready as an auxiliary real outdoor depth prior |
| Wildfire smoke detection | `wildfire-smoke-detection-v1.zip` | 13,518,198,597 | `27abdbe3d3703d9c6fa67bfde136088845726313e148644eb0e948f9a6211e13` | Training-ready for smoke detection |
| Wildfire smoke segmentation | `wildfire-smoke-segmentation-v1.zip` | 464,864,048 | `23134190da8ef71b157764453f3d5575a339fe469878934c70e4972db33eee0e` | Dataset-ready; weak SAM masks and limited human masks |

Total payload: 330,717,305,039 bytes.

## Integrity

The accompanying `*.validation.json` and `*.zip.sha256` files record the checks applied
before publication. All fifteen archives passed:

- full ZIP CRC verification;
- SHA-256 verification of every entry;
- a single training root per archive;
- path-traversal and duplicate-entry rejection;
- cross-source exact-duplicate and split-leakage checks.

The EO4Wildfires materialization contains exactly 31,730 scenes: 20,307 train,
5,077 validation, and 6,346 test.

The cross-view registration bundle contains 390 verified pairs split into 288 train,
57 validation, and 45 test rows across 14 isolated spatial groups. It includes 264
AerialExtreMatch examples and 126 French rural or mountain ODM examples. The private
double-validation lot and the failed RoMa quality probe remain excluded.

The media-triage bundle derives image-level supervision only from verified source boxes and
explicit negatives. It contains 155,044 images split into 107,449 train, 23,689 validation,
and 23,906 test rows across 4,950 isolated groups. Touati and TaMduluza are not included:
their published repository structure does not provide a reliable per-image class contract or
a leakage-free video grouping.

The orchestrator bundle contains 118 deterministic decision examples generated by the current
FireWarning stage contracts and gate engine: 110 stage-gate cases and 8 consensus cases. Its two
synthetic daily workflows cover a nominal path and a contradiction that invokes the final judge
and abstains when raw evidence is unavailable. It contains no operational Référence opérationnelle A or Référence opérationnelle B
fact and never authorizes automatic publication.

The FireSpread_MedEU bundle contains 103 event-isolated sequences and 316 usable cumulative
burned-area targets. It does not claim observed active-front supervision. CrisisFACTS contributes
769 deduplicated facts over 26 event-days, while the structured IMSR bundle contains 15,982
incident-proxy sequences covering 88,208 incident-days; both remain out-of-domain for France until
an independent French validation lot is approved.

The Open Images subset contains 4,398 licensed images split into 3,310 train, 435 validation, and
653 test samples, with no exact pixel leakage. It retains human-verified boxes for ambulances,
helicopters, and fixed-wing aircraft. Open Images has no boxable fire-engine class and does not
identify aircraft by firefighting role, so this bundle is supplemental rather than production-ready.

The TartanAir subset contains 34,742 aligned outdoor RGB, metric-depth, and camera-pose samples
split by complete environment into 18,324 train, 5,838 validation, and 10,580 test rows. It is a
synthetic geometry prior only: local NED poses are not geographic coordinates, and an independent
real rural or mountain camera-pose test remains mandatory before operational use.

The DIODE outdoor bundle contains 17,330 real outdoor RGB images aligned with metric depth and
validity masks, split by complete scene into 13,678 train, 105 validation, and 3,547 test rows.
Its 15 scenes have no split-group leakage. DIODE's official downloadable test partition is not
available through the public archive used here, so the FireWarning splits are deterministically
assigned from complete train and validation scenes and recorded in the source manifest.

The Boreal detection subset contains 6,365 UAV images with 6,340 human smoke boxes and 256
documented empty-image negatives. Collection sites are isolated across 2,910 train, 2,217
validation, and 1,238 test rows. Fifty-two zero-byte labels outside the documented negative set
are quarantined rather than silently converted into negative supervision. The segmentation subset
contains 1,417 image-mask pairs: 40 human masks are strong labels and 1,377 SAM-generated masks
remain weak supervision, recorded separately in every sample and split.

## Licenses and attribution

This repository is a mixed-license collection. There is no single license covering every
payload. Consult `TRAIN_BUNDLE.json` and the source metadata inside each ZIP before use or
redistribution. Included source families declare licenses such as CC BY 4.0,
CC BY-SA 4.0, CC0 1.0, Apache 2.0, MIT, and GPL 3.0, depending on the source.

Operational evaluation packages for Référence opérationnelle A and Référence opérationnelle B are not included. Some openly
licensed third-party training candidates can still document those locations; their original
source URL, author, and license are retained in the corresponding manifest.

## Publication policy

These packages are training inputs, not operational fire reports. They must not be used as
evidence of a current incident, and generated locations or perimeters still require the
FireWarning deterministic gates and human validation before publication.
