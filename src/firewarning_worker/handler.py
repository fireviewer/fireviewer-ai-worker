from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from firewarning_worker.adapters import (
    AdapterFactory,
    UnavailableAdapterFactory,
    adapter_factory_job_scope,
)
from firewarning_worker.boot_clock import BOOT_STARTED_AT
from firewarning_worker.contracts import (
    ResearchInputV1,
    ResearchOutputV1,
    WorkerInput,
    WorkerInputV2,
)
from firewarning_worker.model_registry import (
    RegistryError,
    build_model_group_registry,
    build_registry,
)
from firewarning_worker.security import ConfigurationError, WorkerSettings
from firewarning_worker.session_runner import SessionRunner
from firewarning_worker.stage_contracts import load_stage_contract_registry
from firewarning_worker.v2_runner import from_legacy_output, to_legacy_input
from firewarning_worker.validation import (
    OutputValidationError,
    validate_internal_urls,
    validate_v2_internal_urls,
)

if TYPE_CHECKING:
    from firewarning_worker.spatial_pipeline import DeterministicSpatialPipeline
    from firewarning_worker.v2_burned_area import BurnedAreaAdapter
    from firewarning_worker.v2_pointing import FirePointingAdapter

BOOT_READY_MS = round((perf_counter() - BOOT_STARTED_AT) * 1_000)
_GPU_SESSION_LOCK = threading.Lock()


def _research_failure(
    raw_input: dict[str, Any],
    *,
    detail: str,
    retryable: bool,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    spec = build_registry()["source_research"]
    research_id = raw_input.get("research_id", "INVALID")
    output = ResearchOutputV1.model_validate(
        {
            "research_id": research_id if isinstance(research_id, str) else "INVALID",
            "status": "failed",
            "retryable": retryable,
            "model_run": {
                "model_id": spec.model_id,
                "revision": spec.revision,
                "status": "skipped",
                "started_at": now,
                "finished_at": now,
                "load_ms": 0,
                "inference_ms": 0,
                "error_code": detail[:128],
            },
            "queries": [],
            "candidates": [],
            "validation_errors": [detail[:1_000]],
        }
    )
    return output.model_dump(mode="json")


def _runtime_factory(settings: WorkerSettings) -> AdapterFactory:
    if os.getenv("FW_ENABLE_TRANSFORMERS_RUNTIME", "false").lower() != "true":
        return UnavailableAdapterFactory()
    from firewarning_worker.transformers_adapters import TransformersAdapterFactory

    return TransformersAdapterFactory(
        cache_root=Path(settings.hf_cache_root),
        allowed_hosts=settings.allowed_media_hosts,
        max_download_bytes=settings.max_download_bytes,
        max_cache_bytes=settings.max_media_cache_bytes,
    )


def _runtime_spatial_pipeline(
    factory: AdapterFactory,
) -> DeterministicSpatialPipeline | None:
    from firewarning_worker.transformers_adapters import TransformersAdapterFactory

    if not isinstance(factory, TransformersAdapterFactory):
        return None
    from firewarning_worker.spatial_pipeline import DeterministicSpatialPipeline

    return DeterministicSpatialPipeline(fetcher=factory.fetcher)


def _runtime_fire_pointing_adapter(
    factory: AdapterFactory,
) -> FirePointingAdapter | None:
    from firewarning_worker.transformers_adapters import TransformersAdapterFactory

    if not isinstance(factory, TransformersAdapterFactory):
        return None
    spec = build_registry()["fire_pointing"]
    return factory.create_fire_pointing(spec)


def _runtime_burned_area_adapter(
    factory: AdapterFactory,
) -> BurnedAreaAdapter | None:
    from firewarning_worker.transformers_adapters import TransformersAdapterFactory

    if not isinstance(factory, TransformersAdapterFactory):
        return None
    spec = build_registry()["burned_area"]
    return cast("BurnedAreaAdapter", factory.create_burned_area(spec))


def handle_job(
    job: dict[str, Any],
    *,
    factory: AdapterFactory | None = None,
    spatial_pipeline: DeterministicSpatialPipeline | None = None,
) -> dict[str, Any]:
    raw_input = job.get("input")
    if not isinstance(raw_input, dict):
        return {
            "schema_version": "1.0",
            "batch_id": "INVALID",
            "status": "failed",
            "retryable": False,
            "model_runs": [],
            "items": [],
            "validation_errors": ["input:missing_or_not_an_object"],
            "boot_ms": BOOT_READY_MS,
        }
    requested_schema = raw_input.get("schema_version", "1.0")
    if requested_schema == "research-1.0":
        try:
            research = ResearchInputV1.model_validate(raw_input)
            if not _GPU_SESSION_LOCK.acquire(blocking=False):
                return _research_failure(
                    raw_input,
                    detail="worker:gpu_session_already_active",
                    retryable=True,
                )
            try:
                from firewarning_worker.research_client import run_isolated_research

                return run_isolated_research(research).model_dump(mode="json")
            finally:
                _GPU_SESSION_LOCK.release()
        except (RegistryError, ValidationError) as exc:
            return _research_failure(
                raw_input,
                detail=f"input:{type(exc).__name__}:{exc}",
                retryable=False,
            )
        except Exception as exc:  # isolated service is the runtime failure boundary
            return _research_failure(
                raw_input,
                detail=f"research:{type(exc).__name__}:{exc}",
                retryable=True,
            )
    try:
        settings = WorkerSettings.from_environment()
        batch_v2 = None
        if requested_schema == "2.0":
            batch_v2 = WorkerInputV2.model_validate(raw_input)
            validate_v2_internal_urls(batch_v2, settings.allowed_media_hosts)
            batch = to_legacy_input(batch_v2)
        else:
            batch = WorkerInput.model_validate(raw_input)
            validate_internal_urls(batch.items, settings.allowed_media_hosts)
        registry = build_model_group_registry()
        adapter_factory = factory or _runtime_factory(settings)
        runner = SessionRunner(
            registry=registry,
            adapter_factory=adapter_factory,
            boot_ms=BOOT_READY_MS,
        )
        if not _GPU_SESSION_LOCK.acquire(blocking=False):
            busy: dict[str, Any] = {
                "schema_version": "2.0" if batch_v2 is not None else "1.0",
                "batch_id": batch.batch_id,
                "status": "failed",
                "retryable": True,
                "model_runs": [],
                "items": [],
                "validation_errors": ["worker:gpu_session_already_active"],
                "boot_ms": BOOT_READY_MS,
            }
            if batch_v2 is not None:
                busy.update(
                    {
                        "analysis_id": batch_v2.analysis_window.analysis_id,
                        "orchestration_contract_digest": runner.contracts.digest,
                        "stage_traces": [],
                        "report_draft": None,
                    }
                )
            return busy
        try:
            with adapter_factory_job_scope(adapter_factory):
                execution = runner.run_with_trace(batch)
                if batch_v2 is not None:
                    from firewarning_worker.v2_burned_area import run_burned_area_stage
                    from firewarning_worker.v2_pointing import run_fire_pointing_stage

                    pointing_execution = run_fire_pointing_stage(
                        batch_v2,
                        execution.output,
                        adapter=_runtime_fire_pointing_adapter(adapter_factory),
                        sequence=len(execution.stage_traces) + 1,
                    )
                    burned_area_execution = run_burned_area_stage(
                        batch_v2,
                        adapter=_runtime_burned_area_adapter(adapter_factory),
                        sequence=len(execution.stage_traces) + 2,
                    )
                    resolved_spatial_pipeline = spatial_pipeline or _runtime_spatial_pipeline(
                        adapter_factory
                    )
                    return from_legacy_output(
                        batch_v2,
                        execution.output,
                        stage_traces=execution.stage_traces,
                        candidate_runs=execution.candidate_runs,
                        consensus_results=execution.consensus_results,
                        contract_digest=execution.contract_digest,
                        fire_pointing_execution=pointing_execution,
                        burned_area_execution=burned_area_execution,
                        spatial_pipeline=resolved_spatial_pipeline,
                    ).model_dump(mode="json")
            return execution.output.model_dump(mode="json")
        finally:
            _GPU_SESSION_LOCK.release()
    except (ConfigurationError, OutputValidationError, RegistryError, ValidationError) as exc:
        batch_id = raw_input.get("batch_id", "INVALID")
        failed: dict[str, Any] = {
            "schema_version": "2.0" if requested_schema == "2.0" else "1.0",
            "batch_id": batch_id if isinstance(batch_id, str) else "INVALID",
            "status": "failed",
            "retryable": False,
            "model_runs": [],
            "items": [],
            "validation_errors": [f"input:{type(exc).__name__}:{exc}"],
            "boot_ms": BOOT_READY_MS,
        }
        if requested_schema == "2.0":
            window = raw_input.get("analysis_window")
            failed["analysis_id"] = (
                window.get("analysis_id", "INVALID") if isinstance(window, dict) else "INVALID"
            )
            failed["orchestration_contract_digest"] = load_stage_contract_registry().digest
            failed["stage_traces"] = []
            failed["report_draft"] = None
        return failed


def main() -> None:
    import runpod

    runpod.serverless.start({"handler": handle_job})


if __name__ == "__main__":
    main()
