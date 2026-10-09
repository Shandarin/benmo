from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from benmo_backend.enums import PublicationDecision, SourceTier


@dataclass(frozen=True, slots=True)
class EvidenceForGate:
    is_direct: bool
    quote_verified: bool
    source_tier: SourceTier
    independent_source_key: str | None
    contradiction_level: str = "none"


@dataclass(frozen=True, slots=True)
class EdgeForGate:
    edge_id: uuid.UUID
    evidence: tuple[EvidenceForGate, ...] = ()
    has_executable_spec: bool = False


@dataclass(frozen=True, slots=True)
class TickerExposureForGate:
    exposure_id: uuid.UUID
    has_exposure_evidence: bool


@dataclass(frozen=True, slots=True)
class GateReason:
    code: str
    message: str
    edge_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class PublicationGateResult:
    decision: PublicationDecision
    reasons: tuple[GateReason, ...] = ()
    excluded_ticker_exposure_ids: tuple[uuid.UUID, ...] = ()
    evaluated_edge_count: int = 0


def evaluate_publication_gate(
    edges: Iterable[EdgeForGate],
    ticker_exposures: Iterable[TickerExposureForGate] = (),
) -> PublicationGateResult:
    edge_list = list(edges)
    reasons: list[GateReason] = []
    requires_review = False

    if not edge_list:
        reasons.append(GateReason("chain_has_no_edges", "A public chain must contain an edge."))

    for edge in edge_list:
        valid_evidence = [item for item in edge.evidence if item.quote_verified]
        direct_support_count = sum(item.is_direct for item in valid_evidence)
        if direct_support_count < 1:
            reasons.append(
                GateReason(
                    "direct_support_missing",
                    "At least one direct, quote-verified supporting span is required.",
                    edge.edge_id,
                )
            )

        primary_count = sum(item.source_tier == SourceTier.A for item in valid_evidence)
        secondary_sources = {
            item.independent_source_key
            for item in valid_evidence
            if item.source_tier in {SourceTier.B, SourceTier.C} and item.independent_source_key
        }
        if primary_count == 0 and len(secondary_sources) < 2:
            reasons.append(
                GateReason(
                    "source_independence_insufficient",
                    "Use a primary source or two independent secondary sources.",
                    edge.edge_id,
                )
            )

        if not edge.has_executable_spec:
            reasons.append(
                GateReason(
                    "verification_spec_missing",
                    "Every public edge needs a locked executable verification spec.",
                    edge.edge_id,
                )
            )

        if any(item.contradiction_level == "material" for item in edge.evidence):
            requires_review = True
            reasons.append(
                GateReason(
                    "material_contradiction",
                    "Material contradictory evidence requires a human decision.",
                    edge.edge_id,
                )
            )

    excluded = tuple(
        item.exposure_id for item in ticker_exposures if not item.has_exposure_evidence
    )
    blocking = any(reason.code != "material_contradiction" for reason in reasons)
    if blocking:
        decision = PublicationDecision.REJECT
    elif requires_review:
        decision = PublicationDecision.REVIEW
    else:
        decision = PublicationDecision.PUBLISH

    return PublicationGateResult(
        decision=decision,
        reasons=tuple(reasons),
        excluded_ticker_exposure_ids=excluded,
        evaluated_edge_count=len(edge_list),
    )
