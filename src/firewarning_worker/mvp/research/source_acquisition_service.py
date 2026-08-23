"""HTTP entrypoint for the scale-to-zero Azure CPU source worker."""

from __future__ import annotations

import json
import os
from hmac import compare_digest
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

from pydantic import Field, SecretStr

from firewarning_worker.contracts import SafeIdentifierV2, StrictModel
from firewarning_worker.mvp.research.multimodal_evidence import (
    AzureFederatedBedrockClient,
    AzureManagedIdentityWebTokenProvider,
    BedrockPixtralConfig,
    BedrockPixtralMultimodalProvider,
)
from firewarning_worker.mvp.research.source_acquisition import CpuSourceAcquisitionWorker
from firewarning_worker.mvp.research.source_planner import (
    AutomaticSourceAcquisitionPlanner,
    AutomaticSourcePlannerConfig,
)
from firewarning_worker.mvp.supervision.backend_event_evidence import (
    AzureBackendEventEvidenceAdapter,
    AzureBackendEventEvidenceConfig,
    BackendResearchEvidencePublisher,
    EventEvidenceRepository,
)
from firewarning_worker.research_broker import ResearchBroker

_MAX_REQUEST_BYTES = 4 * 1_024


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


class SourceAcquisitionRequest(StrictModel):
    candidate_id: SafeIdentifierV2


class SourceAcquisitionRunner(Protocol):
    def run_candidate(self, candidate_id: str) -> dict[str, Any]: ...


class SourceAcquisitionOrchestrator:
    def __init__(
        self,
        *,
        repository: EventEvidenceRepository,
        planner: AutomaticSourceAcquisitionPlanner,
        worker: CpuSourceAcquisitionWorker,
    ) -> None:
        self._repository = repository
        self._planner = planner
        self._worker = worker

    def run_candidate(self, candidate_id: str) -> dict[str, Any]:
        durable = self._repository.read(candidate_id)
        plan = self._planner.build(durable)
        receipt = self._worker.run(plan)
        return {
            **receipt.model_dump(mode="json"),
            "planner": "automatic-durable-candidate-v1",
            "query_count": len(plan.queries),
            "domain_policy_count": len(plan.source_policies),
        }


class SourceAcquisitionServiceSettings(StrictModel):
    host: str = Field(default="0.0.0.0", min_length=1, max_length=255)  # noqa: S104
    port: int = Field(default=8080, ge=1, le=65_535)
    worker_token: SecretStr = Field(min_length=32, max_length=4_096)
    broker_control_token: SecretStr = Field(min_length=32, max_length=4_096)
    managed_identity_client_id: str = Field(min_length=36, max_length=36)
    aws_role_arn: str = Field(pattern=r"^arn:aws:iam::\d{12}:role/[A-Za-z0-9+=,.@_/-]+$")
    aws_oidc_audience: str = Field(min_length=8, max_length=512)
    aws_region: str = Field(default="eu-west-3", pattern=r"^[a-z]{2}-[a-z]+-\d$")
    bedrock_model_id: str = Field(
        default="eu.mistral.pixtral-large-2502-v1:0",
        min_length=3,
        max_length=256,
    )
    multimodal_enabled: bool = False
    search_provider_domain: str = Field(default="html.duckduckgo.com", min_length=3)
    search_template: str = Field(
        default="https://html.duckduckgo.com/html/?q={query}", min_length=16
    )
    backend: AzureBackendEventEvidenceConfig

    @classmethod
    def from_env(cls) -> SourceAcquisitionServiceSettings:
        return cls(
            host=os.getenv("FIREVIEWER_SOURCE_WORKER_HOST", "0.0.0.0"),  # noqa: S104
            port=int(os.getenv("PORT", "8080")),
            worker_token=SecretStr(os.environ["FIREVIEWER_SOURCE_WORKER_TOKEN"]),
            broker_control_token=SecretStr(
                os.environ["FIREVIEWER_SOURCE_BROKER_CONTROL_TOKEN"]
            ),
            managed_identity_client_id=os.environ["AZURE_CLIENT_ID"],
            aws_role_arn=os.environ["FIREVIEWER_BEDROCK_ROLE_ARN"],
            aws_oidc_audience=os.environ["FIREVIEWER_AWS_OIDC_AUDIENCE"],
            aws_region=os.getenv("AWS_REGION", "eu-west-3"),
            bedrock_model_id=os.getenv(
                "FIREVIEWER_BEDROCK_MODEL_ID",
                "eu.mistral.pixtral-large-2502-v1:0",
            ),
            multimodal_enabled=_env_bool("FIREVIEWER_MULTIMODAL_ENABLED", False),
            search_provider_domain=os.getenv(
                "FIREVIEWER_SOURCE_SEARCH_PROVIDER_DOMAIN", "html.duckduckgo.com"
            ),
            search_template=os.getenv(
                "FIREVIEWER_SOURCE_SEARCH_TEMPLATE",
                "https://html.duckduckgo.com/html/?q={query}",
            ),
            backend=AzureBackendEventEvidenceConfig(
                base_url=os.environ["FIREVIEWER_BACKEND_BASE_URL"],
                bearer_token=SecretStr(os.environ["FIREVIEWER_BACKEND_TOKEN"]),
                timeout_seconds=float(os.getenv("FIREVIEWER_BACKEND_TIMEOUT_SECONDS", "20")),
            ),
        )


class SourceAcquisitionService:
    def __init__(
        self,
        *,
        settings: SourceAcquisitionServiceSettings,
        runner: SourceAcquisitionRunner | None = None,
    ) -> None:
        self.settings = settings
        if runner is None:
            repository = AzureBackendEventEvidenceAdapter(settings.backend)
            provider = None
            if settings.multimodal_enabled:
                config = BedrockPixtralConfig(
                    region_name=settings.aws_region,
                    model_id=settings.bedrock_model_id,
                )
                provider = BedrockPixtralMultimodalProvider(
                    config,
                    client=AzureFederatedBedrockClient(
                        role_arn=settings.aws_role_arn,
                        region_name=settings.aws_region,
                        web_token_provider=AzureManagedIdentityWebTokenProvider(
                            audience=settings.aws_oidc_audience,
                            managed_identity_client_id=settings.managed_identity_client_id,
                        ),
                    ),
                )
            control_token = settings.broker_control_token.get_secret_value()
            worker = CpuSourceAcquisitionWorker(
                repository=repository,
                publisher=BackendResearchEvidencePublisher(settings.backend),
                broker=ResearchBroker(control_token=control_token),
                broker_control_token=control_token,
                multimodal_evidence_provider=provider,
            )
            runner = SourceAcquisitionOrchestrator(
                repository=repository,
                planner=AutomaticSourceAcquisitionPlanner(
                    AutomaticSourcePlannerConfig(
                        search_provider_domain=settings.search_provider_domain,
                        search_template=settings.search_template,
                    )
                ),
                worker=worker,
            )
        self.runner = runner

    def authorize(self, header: str | None) -> bool:
        expected = f"Bearer {self.settings.worker_token.get_secret_value()}"
        return header is not None and compare_digest(header, expected)

    def run(self, payload: object) -> dict[str, Any]:
        request = SourceAcquisitionRequest.model_validate(payload)
        return self.runner.run_candidate(request.candidate_id)


def _handler_for(service: SourceAcquisitionService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "FireViewerSourceCpu/2.0"

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/healthz":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            self._json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "runtime": "azure-cpu",
                    "planner": "automatic-durable-candidate-v1",
                    "manual_plan_accepted": False,
                    "multimodal_provider": "aws-bedrock-pixtral",
                    "multimodal_model": service.settings.bedrock_model_id,
                    "multimodal_enabled": service.settings.multimodal_enabled,
                    "multimodal_input_scope": "public-web-only",
                    "raw_scraped_content_stored": False,
                    "transcripts_stored": False,
                    "public_media_binaries_stored": False,
                },
            )

        def do_POST(self) -> None:
            if self.path != "/v1/event-evidence/research":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if not service.authorize(self.headers.get("Authorization")):
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= _MAX_REQUEST_BYTES:
                    raise ValueError("request_size_invalid")
                payload = json.loads(self.rfile.read(length))
                result = service.run(payload)
            except Exception as exc:
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": type(exc).__name__, "detail": str(exc)[:1_000]},
                )
                return
            self._json(HTTPStatus.OK, result)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def create_source_acquisition_server(
    service: SourceAcquisitionService,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(
        (service.settings.host, service.settings.port),
        _handler_for(service),
    )


def main() -> None:
    settings = SourceAcquisitionServiceSettings.from_env()
    server = create_source_acquisition_server(SourceAcquisitionService(settings=settings))
    server.serve_forever()


if __name__ == "__main__":
    main()


__all__ = [
    "SourceAcquisitionOrchestrator",
    "SourceAcquisitionRequest",
    "SourceAcquisitionService",
    "SourceAcquisitionServiceSettings",
    "create_source_acquisition_server",
]
