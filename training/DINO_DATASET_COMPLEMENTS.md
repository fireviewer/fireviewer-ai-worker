# DINOv3 dataset complements

This campaign extends the DINOv3 multi-task and cross-view datasets without treating
temporally adjacent video frames as independent scenes or duplicating payloads already
published by FireViewer.

## Source decisions

| Source | Multi-task role | Cross-view role | Current gate |
|---|---|---|---|
| WIT-UAS | Sensor-derived fire masks and fire-base points; person and vehicle boxes are exclusion regions | Approximate-pose validation only | Fire masks must be derived and splits rebuilt by burn site and flight |
| FIReStereo FiresGL | Stereo/temporal weak fire masks, fire-base points, ember and dense-smoke cases | Stereo robustness validation | No upstream fire masks, no metric pose or depth for FiresGL |
| Pyro-SDIS SDIS 77 | Box-guided smoke masks and smoke-column-base points | Excluded unless the same incident is observed from several stations | Reuse the existing FireViewer payload and split by camera and incident date |
| HPWREN FIgLib | Smoke onset, pre-ignition abstention, smoke-column-base points | Same-incident multi-camera pairs only | Index sequences before downloading selected incident archives |
| ALERTWildfire / AlertWest | Distant smoke and hard negatives from approved incident archives | Geolocated multi-station incidents only | Do not scrape live feeds |
| Pyronear Fontainebleau drone | Independent French incident | High-priority multi-vantage incident | Public archive not located yet |
| Wildfire3Data | Not primary | Primary cross-view source | Official release not located yet |

The public Pyronear research repository contains two SDIS 77 DVC indexes (5,350
sequence files and 12,861 annotation-export files). Their configured S3 objects are
not anonymously readable, so they are recorded as upstream acquisition leads and are
not included in the executable download plan. They do not establish that the claimed
Fontainebleau drone incident is publicly available.


The registry is `training/registries/dino-complements-v1.json`.

## Commands

```powershell
$RepoRoot = "<fireviewer-ai-worker>"
$DatasetRoot = "<temporary-dataset-root>"
Set-Location $RepoRoot

# Inspect the complete source and admission plan.
python -m tools.prepare_dino_complements plan

# Verify availability and byte sizes without downloading the FiresGL payload.
python -m tools.prepare_dino_complements probe --source firestereo-firesgl

# Pilot: download only the first FiresGL archive with resumable partial-file support.
python -m tools.prepare_dino_complements download `
  --source firestereo-firesgl `
  --archive-root "$DatasetRoot\archives\firestereo-firesgl" `
  --maximum-assets 1

# Extract the pilot and delete its archive only after a successful non-empty extraction.
python -m tools.prepare_dino_complements extract `
  --source firestereo-firesgl `
  --archive-root "$DatasetRoot\archives\firestereo-firesgl" `
  --output-root "$DatasetRoot\sources\firestereo-firesgl" `
  --maximum-assets 1 `
  --delete-archives
```

The full FiresGL archive set is 43,614,968,427 bytes (40.62 GiB). Only grouped,
temporally sampled frames are admitted to a training manifest. The full sequences are
retained only while producing the offline robustness benchmark.

WIT-UAS acquisition remains isolated from the project because the official downloader
uses its own MinIO client. Its upstream code is not executed by the FireViewer pipeline.
The resulting data must be normalized into burn-site and flight groups before any label
derivation.

Index FIgLib incidents and camera groups without downloading images:

```powershell
python -m tools.index_figlib `
  --output-root "$DatasetRoot\indexes\hpwren-figlib"
```

Only event groups observed by at least two distinct cameras are cross-view candidates.
The current official index contains 517 sequences grouped into 302 events. It exposes
110 multi-camera event groups covering 324 candidate sequences. All frames from one
event remain in the same split.
