from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benmo_backend.domains.publication import (
    EdgeForGate,
    EvidenceForGate,
    PublicationGateResult,
    TickerExposureForGate,
    evaluate_publication_gate,
)
from benmo_backend.enums import EntailmentStatus, SourceTier
from benmo_backend.errors import NotFoundError
from benmo_backend.models import (
    CausalEdge,
    ChainVersion,
    EdgeEvidence,
    EvidenceSpan,
    TickerExposure,
)


def _spec_is_executable(edge: CausalEdge) -> bool:
    if not edge.verification_specs:
        return False
    spec = edge.verification_specs[-1]
    return bool(
        spec.locked_at
        and spec.metric_code
        and spec.source_adapter
        and spec.threshold
        and spec.baseline_rule
        and spec.observation_window
        and spec.comparator_expression.strip()
    )


async def evaluate_chain_version(
    session: AsyncSession, chain_version_id: uuid.UUID
) -> PublicationGateResult:
    version = await session.scalar(select(ChainVersion).where(ChainVersion.id == chain_version_id))
    if version is None:
        raise NotFoundError("Chain version not found.", details={"id": str(chain_version_id)})

    edges = (
        await session.scalars(
            select(CausalEdge)
            .where(CausalEdge.chain_version_id == chain_version_id)
            .options(
                selectinload(CausalEdge.verification_specs),
                selectinload(CausalEdge.evidence_links)
                .selectinload(EdgeEvidence.span)
                .selectinload(EvidenceSpan.document),
            )
            .order_by(CausalEdge.created_at)
        )
    ).all()
    exposures = (
        await session.scalars(
            select(TickerExposure)
            .join(CausalEdge, CausalEdge.id == TickerExposure.edge_id)
            .where(CausalEdge.chain_version_id == chain_version_id)
        )
    ).all()

    gate_edges: list[EdgeForGate] = []
    for edge in edges:
        evidence: list[EvidenceForGate] = []
        for link in edge.evidence_links:
            is_direct_support = bool(
                link.role == "support"
                and link.is_direct
                and link.entailment_status == EntailmentStatus.DIRECTLY_SUPPORTS.value
            )
            evidence.append(
                EvidenceForGate(
                    is_direct=is_direct_support,
                    quote_verified=link.span.quote_verified,
                    source_tier=SourceTier(link.span.document.source_tier),
                    independent_source_key=link.independent_source_key,
                    contradiction_level=link.contradiction_level,
                )
            )
        gate_edges.append(
            EdgeForGate(
                edge_id=edge.id,
                evidence=tuple(evidence),
                has_executable_spec=_spec_is_executable(edge),
            )
        )

    gate_exposures = [
        TickerExposureForGate(
            exposure_id=item.id,
            has_exposure_evidence=bool(item.exposure_evidence),
        )
        for item in exposures
    ]
    return evaluate_publication_gate(gate_edges, gate_exposures)
