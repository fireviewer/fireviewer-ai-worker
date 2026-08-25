# FireViewer deterministic satellite CPU worker

This internal Azure Container App processes official incident/day satellite products. It is
separate from the optional paid SageMaker path and can run with scale-to-zero on CPU.

Implemented deterministic routes:

- Copernicus CLMS Burnt Area Global 300 m daily V4 COG: read the incident AOI from the DOB,
  CP, and BF assets; select the exact local day; threshold probability and burned fraction;
  polygonise selected pixels; clip the result to the incident bounds; publish a sourced
  `burned_area` observation.
- Copernicus Sentinel-3 SLSTR FRP NRT/NTC: stream the exact
  `FRP_MWIR1km_standard.nc` (NRT) or `FRP_in.nc` (NTC) asset to ephemeral storage; validate
  time, position, FRP, uncertainty, footprint, confidence, and the vegetation fire
  classification bit; publish sourced `thermal_hotspot` points.
- Sentinel-2 Level-2A: download the bounded pre-fire/post-fire B04, B8A, B11, B12, and SCL
  assets to ephemeral storage; compute NBR/dNBR on the aligned 20 m grid; exclude cloud,
  shadow, and no-data pixels; and publish a sourced burned-probability mask plus valid coverage.
  Paid Prithvi invocation remains a separate, independently disabled second-opinion path.

NASA FIRMS MODIS and VIIRS hotspots are fetched by the backend official-source connector. Their
reported scan/track footprints are persisted as `thermal_footprint` observations. They can
corroborate spatial evidence but can never be promoted directly to an active front.

The worker never converts a thermal point into a perimeter. Part.4 builds geometry only from
georeferenced observed masks. Thermal points can corroborate or contradict those masks without
being buffered.

## Retention and integrity

- CLMS windows are read directly from the official CDSE S3 endpoint.
- Sentinel-3 NRT/NTC FRP files are deleted when the request finishes.
- Sentinel-2 source assets are limited to 512 MiB per change pair by default and deleted when
  the request finishes.
- Derived observations contain geometry, time, accuracy, numeric metrics, immutable asset
  checksums, processor revision, and source references.
- Raw satellite bytes and CDSE object URIs are not copied into `EventEvidence` claims.
- Satellite products selected for the separate Prithvi materialisation path may be retained in
  the dedicated durable satellite store.

## Required deployment configuration

Deploy with internal TLS ingress, one concurrent replica, `minReplicas=0`, and `maxReplicas=1`.
Use Container Apps secrets for every value marked secret.

| Variable | Purpose |
| --- | --- |
| `FIREVIEWER_SATELLITE_CPU_WORKER_TOKEN` | Secret shared with backend `FV_INCIDENT_DAY_SATELLITE_WORKER_TOKEN`. |
| `FIREVIEWER_BACKEND_BASE_URL` | Existing Azure backend base URL. |
| `FIREVIEWER_BACKEND_TOKEN` | Backend read and deterministic satellite-observation sink token. |
| `FIREVIEWER_CDSE_S3_ACCESS_KEY` | Free CDSE S3 credential, stored only as a Container Apps secret. |
| `FIREVIEWER_CDSE_S3_SECRET_KEY` | Matching free CDSE S3 secret. |
| `FIREVIEWER_SENTINEL2_MAXIMUM_DOWNLOAD_BYTES` | Maximum temporary pre/post download size; defaults to 512 MiB. |
| `FIREVIEWER_SAGEMAKER_GEO_INVOCATION_ENABLED` | Must remain `false` until a separate paid authorization. |

The backend points `FV_INCIDENT_DAY_SATELLITE_WORKER_URL` to this app and automatically sends the
next unprocessed immutable artifact revision to:

```text
POST /v1/incident-day/satellite-observations
```

The request contains only `analysis_id` and `artifact_revision_id`. A caller cannot submit a
raster URL, geometry, threshold, or manually constructed evidence payload.

`GET /healthz` must report `deterministic_satellite_observations_ready=true` before the backend
stage is enabled. If CDSE credentials are absent, the service stays fail-closed and returns
`cdse_s3_credentials_unavailable`; it does not fall back to a paid provider.
