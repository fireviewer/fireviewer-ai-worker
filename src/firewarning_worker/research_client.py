"""Worker-side client for the isolated source-research service."""

from __future__ import annotations

import os
from pathlib import Path

from firewarning_worker.contracts import ResearchInputV1, ResearchOutputV1
from firewarning_worker.research_rpc import call


class ResearchServiceError(RuntimeError):
    pass


def run_isolated_research(research: ResearchInputV1) -> ResearchOutputV1:
    socket_path = Path(os.getenv("FW_RESEARCH_SERVICE_SOCKET", "/run/firewarning/research.sock"))
    response = call(
        socket_path,
        {"action": "run", "input": research.model_dump(mode="json")},
        timeout=float(os.getenv("FW_RESEARCH_SERVICE_TIMEOUT_SECONDS", "900")),
    )
    if response.get("ok") is not True:
        raise ResearchServiceError(str(response.get("error") or "research service failed"))
    output = response.get("output")
    return ResearchOutputV1.model_validate(output)
