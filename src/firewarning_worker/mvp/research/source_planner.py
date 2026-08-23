"""Deterministic source-acquisition plans derived from durable candidates."""

from __future__ import annotations

import json
import re
from hashlib import sha256

from pydantic import Field, model_validator

from firewarning_worker.contracts import StrictModel
from firewarning_worker.mvp.research.source_acquisition import (
    SourceAcquisitionPlan,
    SourceDomainPolicy,
)
from firewarning_worker.mvp.supervision.backend_event_evidence import DurableEventEvidence

_UNSAFE_LABEL_PATTERN = re.compile(r"(?:https?://|@|\+?\d[\d .()-]{7,}\d)", re.IGNORECASE)
_LABEL_CHARACTER_PATTERN = re.compile(r"[^\wÀ-ÖØ-öø-ÿ' -]+", re.UNICODE)


def _policy(
    publisher: str,
    source_type: str,
    independence_weight: float,
) -> SourceDomainPolicy:
    return SourceDomainPolicy.model_validate(
        {
            "publisher": publisher,
            "source_type": source_type,
            "independence_weight": independence_weight,
        }
    )


DEFAULT_SOURCE_POLICIES: dict[str, SourceDomainPolicy] = {
    "interieur.gouv.fr": _policy("French Ministry of Interior", "official", 1.0),
    "pompiers.fr": _policy("Sapeurs-pompiers de France", "official", 0.95),
    "georisques.gouv.fr": _policy("Georisques", "official", 1.0),
    "ec.europa.eu": _policy("European Commission", "official", 1.0),
    "copernicus.eu": _policy("Copernicus", "satellite", 1.0),
    "francetvinfo.fr": _policy("Franceinfo", "press", 0.9),
    "ici.fr": _policy("Ici", "press", 0.9),
    "france24.com": _policy("France 24", "press", 0.9),
    "lemonde.fr": _policy("Le Monde", "press", 0.9),
    "lefigaro.fr": _policy("Le Figaro", "press", 0.85),
    "bfmtv.com": _policy("BFMTV", "press", 0.8),
    "tf1info.fr": _policy("TF1 Info", "press", 0.8),
    "20minutes.fr": _policy("20 Minutes", "press", 0.8),
    "ouest-france.fr": _policy("Ouest-France", "press", 0.9),
    "sudouest.fr": _policy("Sud Ouest", "press", 0.9),
    "ladepeche.fr": _policy("La Depeche", "press", 0.85),
    "midilibre.fr": _policy("Midi Libre", "press", 0.85),
    "laprovence.com": _policy("La Provence", "press", 0.85),
    "nice-matin.com": _policy("Nice-Matin", "press", 0.85),
    "varmatin.com": _policy("Var-Matin", "press", 0.85),
    "corsematin.com": _policy("Corse-Matin", "press", 0.85),
    "ledauphine.com": _policy("Le Dauphine Libere", "press", 0.85),
    "reuters.com": _policy("Reuters", "press", 0.95),
    "apnews.com": _policy("Associated Press", "press", 0.95),
    "euronews.com": _policy("Euronews", "press", 0.85),
    "bbc.com": _policy("BBC", "press", 0.9),
    "theguardian.com": _policy("The Guardian", "press", 0.85),
}


class AutomaticSourcePlannerConfig(StrictModel):
    search_provider_domain: str = "html.duckduckgo.com"
    search_template: str = "https://html.duckduckgo.com/html/?q={query}"
    source_policies: dict[str, SourceDomainPolicy] = Field(
        default_factory=lambda: dict(DEFAULT_SOURCE_POLICIES)
    )
    target_media: int = Field(default=20, ge=20, le=100)
    results_per_page: int = Field(default=20, ge=1, le=50)
    max_pages_per_run: int = Field(default=5, ge=1, le=50)
    max_multimodal_analyses_per_run: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_domains(self) -> AutomaticSourcePlannerConfig:
        normalized = {key.casefold().rstrip(".") for key in self.source_policies}
        if len(normalized) != len(self.source_policies):
            raise ValueError("automatic source domains must be unique")
        if self.search_provider_domain.casefold().rstrip(".") in normalized:
            raise ValueError("search provider must be separate from source domains")
        return self


def _safe_public_label(value: str | None) -> str | None:
    if value is None or _UNSAFE_LABEL_PATTERN.search(value):
        return None
    normalized = " ".join(_LABEL_CHARACTER_PATTERN.sub(" ", value).split())
    if not 2 <= len(normalized) <= 120:
        return None
    return normalized


class AutomaticSourceAcquisitionPlanner:
    """Build a stable plan without accepting user-supplied domains or templates."""

    def __init__(self, config: AutomaticSourcePlannerConfig | None = None) -> None:
        self.config = config or AutomaticSourcePlannerConfig()

    def build(self, durable: DurableEventEvidence) -> SourceAcquisitionPlan:
        observed = durable.event.time_window.from_at
        date = observed.date().isoformat() if observed is not None else ""
        label = _safe_public_label(durable.viewpoint_label)
        if label:
            queries = (
                f'incendie "{label}" {date}'.strip(),
                f'feu de foret "{label}" {date}'.strip(),
                f'evacuation pompiers "{label}" {date}'.strip(),
            )
        else:
            queries = (
                f"incendie {date}".strip(),
                f"feu de foret {date}".strip(),
                f"evacuation pompiers {date}".strip(),
            )
        policies = {
            domain.casefold().rstrip("."): policy
            for domain, policy in self.config.source_policies.items()
        }
        identity = json.dumps(
            {
                "candidate_id": durable.event.event_id,
                "queries": queries,
                "domains": sorted(policies),
                "target_media": self.config.target_media,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return SourceAcquisitionPlan(
            candidate_id=durable.event.event_id,
            plan_id=f"PLAN-AUTO-{sha256(identity.encode('utf-8')).hexdigest()[:24]}",
            queries=queries,
            allowed_domains=tuple(sorted(policies)),
            source_policies=policies,
            search_provider_domain=self.config.search_provider_domain,
            search_template=self.config.search_template,
            target_media=self.config.target_media,
            results_per_page=self.config.results_per_page,
            max_pages_per_run=self.config.max_pages_per_run,
            max_multimodal_analyses_per_run=(
                self.config.max_multimodal_analyses_per_run
            ),
        )


__all__ = [
    "DEFAULT_SOURCE_POLICIES",
    "AutomaticSourceAcquisitionPlanner",
    "AutomaticSourcePlannerConfig",
]
