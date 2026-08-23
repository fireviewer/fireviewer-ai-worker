from __future__ import annotations

import json
import socket
import threading
from http.client import HTTPConnection

from firewarning_worker.mvp.research.source_acquisition_service import (
    SourceAcquisitionService,
    SourceAcquisitionServiceSettings,
    create_source_acquisition_server,
)
from firewarning_worker.mvp.supervision.backend_event_evidence import (
    AzureBackendEventEvidenceConfig,
)


class _Runner:
    def __init__(self) -> None:
        self.candidate_ids: list[str] = []

    def run_candidate(self, candidate_id: str):
        self.candidate_ids.append(candidate_id)
        return {
            "candidate_id": candidate_id,
            "plan_id": "PLAN-AUTO-1",
            "media_count": 20,
            "claim_count": 0,
        }


def _free_port() -> int:
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        return int(stream.getsockname()[1])


def test_source_service_accepts_only_candidate_id_and_builds_no_manual_plan() -> None:
    runner = _Runner()
    token = "worker-" + ("w" * 40)
    settings = SourceAcquisitionServiceSettings(
        host="127.0.0.1",
        port=_free_port(),
        worker_token=token,
        broker_control_token="broker-" + ("b" * 40),
        managed_identity_client_id="22222222-2222-4222-8222-222222222222",
        aws_role_arn="arn:aws:iam::123456789012:role/fireviewer-source-bedrock",
        aws_oidc_audience="api://33333333-3333-4333-8333-333333333333",
        backend=AzureBackendEventEvidenceConfig(
            base_url="https://backend.fireviewer.test",
            bearer_token="backend-" + ("x" * 40),
        ),
    )
    service = SourceAcquisitionService(settings=settings, runner=runner)
    server = create_source_acquisition_server(service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    body = json.dumps({"candidate_id": "EC-SERVICE-1"}).encode()
    try:
        connection = HTTPConnection("127.0.0.1", settings.port, timeout=5)
        connection.request("GET", "/healthz")
        health = connection.getresponse()
        health_payload = json.loads(health.read())
        assert health.status == 200
        assert health_payload["runtime"] == "azure-cpu"
        assert health_payload["manual_plan_accepted"] is False
        assert health_payload["multimodal_provider"] == "aws-bedrock-pixtral"
        assert health_payload["multimodal_enabled"] is False
        assert health_payload["raw_scraped_content_stored"] is False

        connection.request(
            "POST",
            "/v1/event-evidence/research",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        denied = connection.getresponse()
        denied.read()
        assert denied.status == 401

        connection.request(
            "POST",
            "/v1/event-evidence/research",
            body=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        accepted = connection.getresponse()
        accepted_payload = json.loads(accepted.read())
        assert accepted.status == 200
        assert accepted_payload["media_count"] == 20
        assert accepted_payload["claim_count"] == 0
        assert runner.candidate_ids == ["EC-SERVICE-1"]

        oversized_plan = json.dumps(
            {
                "candidate_id": "EC-SERVICE-1",
                "queries": ["manual plan is forbidden"],
            }
        ).encode()
        connection.request(
            "POST",
            "/v1/event-evidence/research",
            body=oversized_plan,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        rejected = connection.getresponse()
        rejected.read()
        assert rejected.status == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
