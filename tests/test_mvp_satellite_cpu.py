from __future__ import annotations

import io
import json
import shutil
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from botocore.exceptions import ClientError
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

from firewarning_worker.mvp.contracts import EventEvidenceV1
from firewarning_worker.mvp.contracts.common import TimeWindow
from firewarning_worker.mvp.gpu.sagemaker_service import GeoGpuResponse
from firewarning_worker.mvp.satellite_cpu import (
    AzureFederatedSageMakerAsyncProvider,
    CanonicalPrithviRasterBuilder,
    PreparedSatelliteRaster,
    SageMakerAsyncConfig,
    SatelliteCpuError,
    SatelliteCpuWorker,
    build_prithvi_request,
)
from firewarning_worker.mvp.satellite_observations import (
    ClmsRasterWindow,
    SatelliteAssetReceipt,
    SatelliteObservationCpuWorker,
    _frp_sample_count,
    _validate_clms_window_size,
)
from firewarning_worker.mvp.supervision.backend_event_evidence import (
    BackendIncidentDaySatelliteArtifact,
    DurableEventEvidence,
)

_BANDS = ("B02", "B03", "B04", "B8A", "B11", "B12")
_DESCRIPTIONS = ("BLUE", "GREEN", "RED", "NIR_NARROW", "SWIR_1", "SWIR_2")


def test_clms_window_pixel_limit_is_enforced_before_raster_read() -> None:
    with pytest.raises(SatelliteCpuError, match="clms_satellite_window_too_large"):
        _validate_clms_window_size(width=2_001, height=2_000, maximum_pixels=4_000_000)


def test_sentinel3_sample_limit_is_enforced_before_netcdf_read() -> None:
    class OversizedVariable:
        shape = (500_001,)

    with pytest.raises(SatelliteCpuError, match="sentinel3_frp_sample_limit_exceeded"):
        _frp_sample_count(OversizedVariable())


def _write_sources(directory: Path) -> tuple[dict[str, Path], tuple[float, float, float, float]]:
    paths: dict[str, Path] = {}
    crs = "EPSG:32631"
    full_bounds = (500_000.0, 4_999_600.0, 500_400.0, 5_000_000.0)
    bbox = transform_bounds(crs, "EPSG:4326", *full_bounds, densify_pts=21)
    for index, band in enumerate(_BANDS, start=1):
        resolution = 10 if band in {"B02", "B03", "B04"} else 20
        size = 40 if resolution == 10 else 20
        path = directory / f"{band}.jp2"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=size,
            height=size,
            count=1,
            dtype="uint16",
            crs=crs,
            transform=from_origin(500_000, 5_000_000, resolution, resolution),
            nodata=0,
        ) as dataset:
            dataset.write(np.full((size, size), index * 1_000, dtype=np.uint16), 1)
        paths[band] = path
    return paths, tuple(float(value) for value in bbox)


def _artifact(acquired_at: datetime) -> BackendIncidentDaySatelliteArtifact:
    return BackendIncidentDaySatelliteArtifact.model_validate(
        {
            "artifact_revision_id": "EAR-CDSE-20260824",
            "provider_key": "copernicus-cdse",
            "collection_key": "sentinel-2-l2a",
            "semantic_role": "raw_earth_observation",
            "external_product_id": "S2B_PRODUCT_20260824",
            "source_url": "https://catalogue.dataspace.copernicus.eu/product",
            "content_hash": "a" * 64,
            "acquisition_start_at": acquired_at.isoformat(),
            "native_crs": "EPSG:32631",
            "footprint_geojson": {
                "type": "Polygon",
                "coordinates": [[[2, 44], [3, 44], [3, 46], [2, 46], [2, 44]]],
            },
            "resolution_m": 20,
            "quality_flags": {"eo:cloud_cover": 12.5},
            "license": "Copernicus Data Space Ecosystem terms",
            "attribution": "Contains modified Copernicus Sentinel data 2026",
            "materialization_state": "materialized",
            "materialization_bundle_id": "SMB-CDSE-20260824",
            "materialization_manifest_sha256": "b" * 64,
            "prithvi_bands": [
                {
                    "canonical_band": band,
                    "asset_name": band,
                    "source_checksum": "1220" + (f"{index:x}" * 64)[:64],
                    "content_sha256": f"{index:x}" * 64,
                    "size_bytes": 1_024,
                    "media_type": "image/jp2",
                    "gsd_m": 20,
                    "proj_code": "EPSG:32631",
                    "proj_shape": [20, 20],
                    "proj_transform": [20, 0, 500000, 0, -20, 5000000],
                    "content_path": (
                        "/api/v1/internal/satellite-materializations/"
                        f"SMB-CDSE-20260824/bands/{band}/content"
                    ),
                }
                for index, band in enumerate(_BANDS, start=1)
            ],
        }
    )


class _Repository:
    def __init__(self, durable: DurableEventEvidence) -> None:
        self.durable = durable

    def read(self, event_id: str) -> DurableEventEvidence:
        assert event_id == self.durable.event.event_id
        return self.durable


class _Fetcher:
    ephemeral_directory: Path | None = None
    bbox: tuple[float, float, float, float] | None = None

    def fetch(self, *, artifact, directory: Path):
        assert artifact.artifact_revision_id == "EAR-CDSE-20260824"
        self.ephemeral_directory = directory
        paths, self.bbox = _write_sources(directory)
        return paths


class _Provider:
    model_id = "ibm-nasa-geospatial/Prithvi-EO-2.0-300M-BurnScars"
    model_revision = "a3f2c410e45b8ac7417976614528a872f024d831"

    def __init__(self, geometry: dict[str, Any]) -> None:
        self.geometry = geometry
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        item = request.worker_input.items[0]
        assert tuple(item.satellite.bands) == _DESCRIPTIONS
        assert request.payloads[0].content_sha256
        annotation_id = "SA-CDSE-20260824"
        return GeoGpuResponse.model_validate(
            {
                "schema": "fireviewer.geo-gpu-response.v1",
                "request_id": request.request_id,
                "operation": "prithvi.burned_area",
                "status": "completed",
                "model_id": self.model_id,
                "model_revision": self.model_revision,
                "result": {
                    "annotations": {
                        item.input_id: [
                            {
                                "annotation_id": annotation_id,
                                "evidence_id": item.input_id,
                                "evidence_kind": "satellite_image",
                                "semantic_anchor": "burned_area_polygon",
                                "source_geometry_normalized": {
                                    "type": "Polygon",
                                    "coordinates": [
                                        [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.1]]
                                    ],
                                },
                                "model_score": 0.88,
                            }
                        ]
                    },
                    "spatial_proposals": {
                        item.input_id: [
                            {
                                "proposal_id": "SP-CDSE-20260824",
                                "annotation_id": annotation_id,
                                "status": "projected_geometry",
                                "proposal_kind": "burned_area_polygon",
                                "observed_at": item.satellite.acquired_at.isoformat(),
                                "geometry_origin": "SATELLITE_GEOTRANSFORM",
                                "geometry_geojson": self.geometry,
                                "horizontal_accuracy_m": item.satellite.resolution_m,
                                "reference_bundle_sha256": (
                                    request.worker_input.reference_bundle.manifest_sha256
                                ),
                                "uncertainty_codes": ["burned_area_model_proposal"],
                            }
                        ]
                    },
                },
                "reason_codes": [],
            }
        )


class _Publisher:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def publish(self, *, candidate_id: str, payload):
        assert candidate_id == payload["analysis_id"]
        self.payloads.append(dict(payload))
        return None


class _ObservationPublisher:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def publish(self, *, candidate_id: str, payload):
        assert candidate_id == payload["analysis_id"]
        self.payloads.append(dict(payload))
        return None


class _LocalObservationReader:
    def __init__(
        self,
        *,
        clms_paths: dict[str, Path] | None = None,
        frp_path: Path | None = None,
    ) -> None:
        self.clms_paths = clms_paths
        self.frp_path = frp_path
        self.frp_ephemeral_path: Path | None = None

    def read_clms_window(self, *, assets, bbox):
        assert self.clms_paths is not None
        arrays = []
        masks = []
        receipts = []
        transform = None
        for asset in assets:
            path = self.clms_paths[asset.asset_name]
            with rasterio.open(path) as dataset:
                masked = dataset.read(1, masked=True)
                transform = dataset.transform
            arrays.append(
                np.asarray(masked.filled(0), dtype=np.float64) * float(asset.raster_scale)
            )
            masks.append(~np.ma.getmaskarray(masked))
            content = path.read_bytes()
            receipts.append(
                SatelliteAssetReceipt(
                    asset_name=asset.asset_name,
                    source_checksum=asset.file_checksum,
                    derived_content_sha256=sha256(content).hexdigest(),
                    bytes_read=len(content),
                )
            )
        assert transform is not None
        return ClmsRasterWindow(
            day_of_burn=arrays[0],
            burn_probability=arrays[1],
            burn_fraction=arrays[2],
            valid_masks=tuple(masks),
            transform=transform,
            receipts=tuple(receipts),
        )

    def fetch_frp_file(self, *, asset, output_path: Path):
        assert self.frp_path is not None
        content = self.frp_path.read_bytes()
        assert len(content) == asset.file_size_bytes
        shutil.copyfile(self.frp_path, output_path)
        self.frp_ephemeral_path = output_path
        return SatelliteAssetReceipt(
            asset_name=asset.asset_name,
            source_checksum=asset.file_checksum,
            derived_content_sha256=sha256(content).hexdigest(),
            bytes_read=len(content),
        )


def test_builder_aligns_six_bands_on_b11_grid(tmp_path: Path) -> None:
    paths, bbox = _write_sources(tmp_path)
    output = CanonicalPrithviRasterBuilder().build(
        band_paths=paths,
        incident_bbox=bbox,
        output_path=tmp_path / "canonical.tif",
    )

    with rasterio.open(output.path) as dataset:
        assert dataset.count == 6
        assert dataset.descriptions == _DESCRIPTIONS
        assert dataset.res == (20, 20)
        assert dataset.width == 20
        assert dataset.height == 20
        assert dataset.read(1).mean() == 1_000
        assert dataset.read(6).mean() == 6_000
    assert output.sha256
    assert output.size_bytes == output.path.stat().st_size


def test_worker_uses_ephemeral_bands_and_publishes_only_derived_geometry() -> None:
    acquired_at = datetime(2026, 8, 24, 10, tzinfo=UTC)
    probe_directory = Path("unused")
    _paths, bbox = _write_sources_for_bbox_only(probe_directory, acquired_at)
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [bbox[0], bbox[1]],
                [bbox[2], bbox[1]],
                [bbox[2], bbox[3]],
                [bbox[0], bbox[1]],
            ]
        ],
    }
    durable = DurableEventEvidence(
        event=EventEvidenceV1(
            event_id="AN-CDSE-20260824",
            time_window=TimeWindow(
                from_at=datetime(2026, 8, 23, 22, tzinfo=UTC),
                to_at=datetime(2026, 8, 24, 22, tzinfo=UTC),
            ),
        ),
        media_locations=(),
        vision_artifacts=(),
        upload_locations=(),
        prior_fire_states=(),
        geospatial_checks=(),
        geographic_references=(),
        source_revision_sha256="c" * 64,
        incident_id="FR-26-00001",
        research_target_kind="incident_day",
        satellite_artifact_tickets=(_artifact(acquired_at),),
        incident_day_episode_id="EP-CDSE-20260824",
        incident_day_local_date=date(2026, 8, 24),
        incident_day_timezone="Europe/Paris",
        incident_day_bbox=bbox,
    )
    fetcher = _Fetcher()
    provider = _Provider(geometry)
    publisher = _Publisher()

    receipt = SatelliteCpuWorker(
        repository=_Repository(durable),
        band_fetcher=fetcher,
        raster_builder=CanonicalPrithviRasterBuilder(),
        provider=provider,
        publisher=publisher,
    ).run(durable.event.event_id)

    assert receipt.processed == 1
    assert receipt.statuses == ("completed",)
    assert len(provider.requests) == 1
    assert len(publisher.payloads) == 1
    persisted = publisher.payloads[0]
    assert persisted["spatial_proposals"][0]["geometry_geojson"] == geometry
    assert "content_base64" not in str(persisted)
    assert persisted["prithvi_input_sha256"]
    assert fetcher.ephemeral_directory is not None
    assert not fetcher.ephemeral_directory.exists()


def _write_sources_for_bbox_only(
    _directory: Path, _acquired_at: datetime
) -> tuple[dict[str, Path], tuple[float, float, float, float]]:
    full_bounds = (500_000.0, 4_999_600.0, 500_400.0, 5_000_000.0)
    bbox = transform_bounds("EPSG:32631", "EPSG:4326", *full_bounds, densify_pts=21)
    return {}, tuple(float(value) for value in bbox)


def _client_error(status: int, operation: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": str(status), "Message": "test"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        operation,
    )


def test_sagemaker_async_poll_resumes_without_a_second_paid_invocation(
    tmp_path: Path,
) -> None:
    acquired_at = datetime(2026, 8, 24, 10, tzinfo=UTC)
    raster_path = tmp_path / "canonical.tif"
    raster_path.write_bytes(b"canonical-six-band-raster")
    raster = PreparedSatelliteRaster(
        path=raster_path,
        sha256=sha256(raster_path.read_bytes()).hexdigest(),
        size_bytes=raster_path.stat().st_size,
        crs="EPSG:32631",
        width=20,
        height=20,
        geotransform=(500_000, 20, 0, 5_000_000, 0, -20),
        bbox_wgs84=(2.9, 45.0, 3.0, 45.1),
        resolution_m=20,
    )
    durable = DurableEventEvidence(
        event=EventEvidenceV1(
            event_id="AN-CDSE-RESUME",
            time_window=TimeWindow(
                from_at=datetime(2026, 8, 23, 22, tzinfo=UTC),
                to_at=datetime(2026, 8, 24, 22, tzinfo=UTC),
            ),
        ),
        media_locations=(),
        vision_artifacts=(),
        upload_locations=(),
        prior_fire_states=(),
        geospatial_checks=(),
        geographic_references=(),
        source_revision_sha256="c" * 64,
        incident_id="FR-26-00001",
        research_target_kind="incident_day",
        satellite_artifact_tickets=(_artifact(acquired_at),),
        incident_day_episode_id="EP-CDSE-RESUME",
        incident_day_local_date=date(2026, 8, 24),
        incident_day_timezone="Europe/Paris",
        incident_day_bbox=raster.bbox_wgs84,
    )
    request = build_prithvi_request(
        durable=durable,
        artifact=durable.satellite_artifact_tickets[0],
        raster=raster,
        request_id="GEO-CDSE-RESUME",
    )
    expected = _Provider(
        {
            "type": "Polygon",
            "coordinates": [[[2.9, 45.0], [3.0, 45.0], [3.0, 45.1], [2.9, 45.0]]],
        }
    ).invoke(request)

    class S3:
        def __init__(self) -> None:
            self.objects: dict[str, bytes] = {}
            self.output_ready = False

        def put_object(self, *, Bucket, Key, Body, **kwargs):
            assert Bucket == "fireviewer-geo-ai-123456789012-eu-west-3"
            if kwargs.get("IfNoneMatch") == "*" and Key in self.objects:
                raise _client_error(412, "PutObject")
            if kwargs.get("IfMatch") is not None and Key not in self.objects:
                raise _client_error(412, "PutObject")
            self.objects[Key] = bytes(Body)
            return {"ETag": '"etag-1"'}

        def get_object(self, *, Bucket, Key):
            assert Bucket == "fireviewer-geo-ai-123456789012-eu-west-3"
            if Key == "async/output/result.json" and self.output_ready:
                body = json.dumps(
                    expected.model_dump(mode="json", by_alias=True),
                    separators=(",", ":"),
                ).encode()
                return {"Body": io.BytesIO(body)}
            if Key not in self.objects:
                raise _client_error(404, "GetObject")
            return {"Body": io.BytesIO(self.objects[Key])}

        def head_object(self, *, Bucket, Key):
            assert Bucket == "fireviewer-geo-ai-123456789012-eu-west-3"
            if Key == "async/output/result.json" and self.output_ready:
                return {"ContentLength": 1}
            raise _client_error(404, "HeadObject")

    class Runtime:
        def __init__(self) -> None:
            self.invocations = 0

        def invoke_endpoint_async(self, **kwargs):
            self.invocations += 1
            assert kwargs["InferenceId"] == request.request_id
            return {
                "OutputLocation": (
                    "s3://fireviewer-geo-ai-123456789012-eu-west-3/async/output/result.json"
                )
            }

    now = [datetime(2026, 8, 24, 12, tzinfo=UTC)]
    s3 = S3()
    runtime = Runtime()
    provider = AzureFederatedSageMakerAsyncProvider(
        SageMakerAsyncConfig(
            region_name="eu-west-3",
            role_arn="arn:aws:iam::123456789012:role/fireviewer-geo",
            endpoint_name="fireviewer-geo-async-0123456789abcdef",
            bucket_name="fireviewer-geo-ai-123456789012-eu-west-3",
            maximum_wait_seconds=30,
            poll_seconds=10,
        ),
        web_token_provider=lambda: "unused",
        sts_client=object(),
        clock=lambda: now[0],
        sleeper=lambda seconds: now.__setitem__(0, now[0] + timedelta(seconds=seconds)),
    )
    provider._s3 = s3
    provider._runtime = runtime
    provider._expires_at = now[0] + timedelta(hours=1)

    with pytest.raises(SatelliteCpuError, match="sagemaker_async_timeout") as first:
        provider.invoke(request)
    assert first.value.retryable is True
    assert runtime.invocations == 1

    s3.output_ready = True
    resumed = provider.invoke(request)

    assert resumed.request_id == request.request_id
    assert runtime.invocations == 1


def _observation_artifact(
    *,
    collection_key: str,
    processor: str,
    assets: list[dict[str, Any]],
    acquired_at: datetime,
    resolution_m: float,
) -> BackendIncidentDaySatelliteArtifact:
    return BackendIncidentDaySatelliteArtifact.model_validate(
        {
            "artifact_revision_id": f"EAR-{sha256(collection_key.encode()).hexdigest()[:24]}",
            "provider_key": "copernicus-cdse",
            "collection_key": collection_key,
            "semantic_role": "interpreted_observation",
            "external_product_id": f"PRODUCT-{processor}",
            "source_url": "https://stac.dataspace.copernicus.eu/v1/item",
            "content_hash": "a" * 64,
            "acquisition_start_at": acquired_at.isoformat(),
            "native_crs": "EPSG:4326",
            "footprint_geojson": {
                "type": "Polygon",
                "coordinates": [[[-180, -60], [180, -60], [180, 80], [-180, 80], [-180, -60]]],
            },
            "resolution_m": resolution_m,
            "quality_flags": {
                "satellite_observation_processor": processor,
                "satellite_observation_assets": assets,
            },
            "license": "Copernicus data policy",
            "attribution": "European Union Copernicus programme",
            "materialization_state": "not_required",
        }
    )


def _observation_durable(
    artifact: BackendIncidentDaySatelliteArtifact,
) -> DurableEventEvidence:
    return DurableEventEvidence(
        event=EventEvidenceV1(
            event_id="AN-DIE-20260709",
            time_window=TimeWindow(
                from_at=datetime(2026, 7, 8, 22, tzinfo=UTC),
                to_at=datetime(2026, 7, 9, 22, tzinfo=UTC),
            ),
        ),
        media_locations=(),
        vision_artifacts=(),
        upload_locations=(),
        prior_fire_states=(),
        geospatial_checks=(),
        geographic_references=(),
        source_revision_sha256="b" * 64,
        incident_id="FR-26-00001",
        research_target_kind="incident_day",
        satellite_artifact_tickets=(artifact,),
        incident_day_episode_id="E01",
        incident_day_local_date=date(2026, 7, 9),
        incident_day_timezone="Europe/Paris",
        incident_day_bbox=(5.36, 44.74, 5.38, 44.76),
    )


def test_clms_daily_cogs_produce_a_clipped_burn_scar_without_raw_rasters(
    tmp_path: Path,
) -> None:
    target_day = date(2026, 7, 9).timetuple().tm_yday
    transform = from_origin(5.36, 44.76, 0.005, 0.005)
    raw_arrays = {
        "ba300_dob_nrt": np.array(
            [[0, 0, 0, 0], [0, target_day, target_day, 0], [0, target_day, 0, 0], [0, 0, 0, 0]],
            dtype=np.int16,
        ),
        "ba300_cp_nrt": np.array(
            [[0, 0, 0, 0], [0, 900, 800, 0], [0, 700, 0, 0], [0, 0, 0, 0]],
            dtype=np.int16,
        ),
        "ba300_bf_nrt": np.array(
            [[0, 0, 0, 0], [0, 600, 500, 0], [0, 400, 0, 0], [0, 0, 0, 0]],
            dtype=np.int16,
        ),
    }
    paths: dict[str, Path] = {}
    asset_payloads: list[dict[str, Any]] = []
    for asset_name, values in raw_arrays.items():
        path = tmp_path / f"{asset_name}.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=4,
            height=4,
            count=1,
            dtype="int16",
            crs="EPSG:4326",
            transform=transform,
            nodata=-1,
        ) as dataset:
            dataset.write(values, 1)
        paths[asset_name] = path
        asset_payloads.append(
            {
                "asset_name": asset_name,
                "object_uri": f"s3://eodata/CLMS/test/{asset_name}.tif",
                "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
                "file_size_bytes": path.stat().st_size,
                "file_checksum": sha256(path.read_bytes()).hexdigest(),
                "proj_code": "EPSG:4326",
                "proj_shape": [4, 4],
                "proj_transform": list(transform.to_gdal()),
                "nodata": -1,
                "data_type": "int16",
                "raster_scale": 1 if asset_name == "ba300_dob_nrt" else 0.001,
            }
        )
    burned_area_collection = "clms_ba_global_300m_daily_v4_cog"
    artifact = _observation_artifact(
        collection_key=burned_area_collection,
        processor="clms_burned_area_daily_v1",
        assets=asset_payloads,
        acquired_at=datetime(2026, 7, 9, tzinfo=UTC),
        resolution_m=300,
    )
    durable = _observation_durable(artifact)
    publisher = _ObservationPublisher()

    receipt = SatelliteObservationCpuWorker(
        repository=_Repository(durable),
        asset_reader=_LocalObservationReader(clms_paths=paths),
        publisher=publisher,
    ).run(durable.event.event_id, artifact.artifact_revision_id)

    assert receipt.status == "completed"
    assert len(publisher.payloads) == 1
    payload = publisher.payloads[0]
    assert payload["raw_satellite_content_stored"] is False
    assert len(payload["asset_receipts"]) == 3
    assert len(payload["observations"]) == 1
    observation = payload["observations"][0]
    assert observation["geometry_geojson"]["type"] in {"Polygon", "MultiPolygon"}
    assert observation["metrics"]["pixel_count"] == 3
    assert observation["metrics"]["target_day_of_year"] == target_day
    assert "object_uri" not in str(payload)


@pytest.mark.parametrize(
    ("collection_key", "asset_name", "confidence_variable"),
    [
        ("sentinel-3-sl-2-frp-ntc", "FRP_in", "confidence"),
        (
            "sentinel-3-sl-2-frp-nrt",
            "FRP_MWIR1km_STANDARD",
            "confidence_level",
        ),
    ],
)
def test_sentinel3_frp_netcdf_produces_only_in_bbox_confident_hotspots(
    tmp_path: Path,
    collection_key: str,
    asset_name: str,
    confidence_variable: str,
) -> None:
    import h5py

    source_path = tmp_path / f"source-{asset_name}.nc"
    time_origin = datetime(2000, 1, 1, tzinfo=UTC)
    observation_times = [
        datetime(2026, 7, 9, 10, tzinfo=UTC),
        datetime(2026, 7, 9, 10, 1, tzinfo=UTC),
        datetime(2026, 7, 9, 10, 2, tzinfo=UTC),
    ]
    with h5py.File(source_path, "w") as dataset:
        dataset.create_dataset("latitude", data=[44.75, 44.751, 45.2], dtype="f8")
        dataset.create_dataset("longitude", data=[5.37, 5.371, 6.0], dtype="f8")
        dataset.create_dataset("FRP_MWIR", data=[18.5, 9.0, 80.0], dtype="f8")
        dataset.create_dataset("FRP_uncertainty_MWIR", data=[1.2, 2.0, 1.0], dtype="f8")
        dataset.create_dataset("IFOV_area", data=[1_000_000] * 3, dtype="f8")
        dataset.create_dataset(confidence_variable, data=[90, 20, 95], dtype="i2")
        dataset.create_dataset("classification", data=[1, 1, 2], dtype="i2")
        time_variable = dataset.create_dataset(
            "time",
            data=[
                int((value - time_origin).total_seconds() * 1_000_000)
                for value in observation_times
            ],
            dtype="i8",
        )
        time_variable.attrs["units"] = "microseconds since 2000-01-01 00:00:00 UTC"
    asset_payload = {
        "asset_name": asset_name,
        "object_uri": (f"s3://eodata/Sentinel-3/SLSTR/SL_2_FRP___/2026/07/09/{asset_name}.nc"),
        "media_type": "application/netcdf",
        "file_size_bytes": source_path.stat().st_size,
        "file_checksum": sha256(source_path.read_bytes()).hexdigest(),
    }
    artifact = _observation_artifact(
        collection_key=collection_key,
        processor="sentinel3_frp_v1",
        assets=[asset_payload],
        acquired_at=datetime(2026, 7, 9, 10, tzinfo=UTC),
        resolution_m=1_000,
    )
    durable = _observation_durable(artifact)
    publisher = _ObservationPublisher()
    reader = _LocalObservationReader(frp_path=source_path)

    receipt = SatelliteObservationCpuWorker(
        repository=_Repository(durable),
        asset_reader=reader,
        publisher=publisher,
        minimum_frp_confidence=0.3,
    ).run(durable.event.event_id, artifact.artifact_revision_id)

    assert receipt.status == "completed"
    assert reader.frp_ephemeral_path is not None
    assert not reader.frp_ephemeral_path.exists()
    payload = publisher.payloads[0]
    assert payload["raw_satellite_content_stored"] is False
    assert len(payload["observations"]) == 1
    observation = payload["observations"][0]
    assert observation["geometry_geojson"] == {"type": "Point", "coordinates": [5.37, 44.75]}
    assert observation["metrics"]["frp_mwir_mw"] == 18.5
    assert observation["metrics"]["provider_confidence"] == 0.9
    assert "object_uri" not in str(payload)
