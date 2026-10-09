from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benmo_backend.dependencies import get_session
from benmo_backend.enums import AnalysisStatus, ChainStatus
from benmo_backend.errors import NotFoundError
from benmo_backend.models import (
    Analysis,
    CausalEdge,
    Chain,
    ChainVersion,
    EdgeEvidence,
    Event,
    EvidenceSpan,
    VerificationSpec,
)
from benmo_backend.schemas import (
    ChainSummary,
    EdgeRead,
    NodeRead,
    PublicAnalysisDetail,
    PublicAnalysisSummary,
    PublicChainGraph,
    PublicChainVersionRead,
    PublicEdgeEvidenceRead,
    PublicEventRead,
    VerificationHistory,
    VerificationRunRead,
    VerificationSpecRead,
)

router = APIRouter(prefix="/public/analyses", tags=["public"])


def _published_chain(event: Event) -> Chain | None:
    return next(
        (
            chain
            for chain in event.chains
            if chain.status == ChainStatus.PUBLISHED.value
            and chain.current_version_id is not None
            and chain.current_version is not None
            and chain.current_version.status == "published"
        ),
        None,
    )


def _summary(analysis: Analysis, chain: Chain) -> PublicAnalysisSummary:
    assert analysis.event is not None
    assert chain.published_at is not None
    return PublicAnalysisSummary(
        public_slug=analysis.public_slug,
        title=analysis.event.title,
        description=analysis.event.description,
        category=analysis.event.category,
        occurred_at=analysis.event.occurred_at,
        weakest_confidence_grade=chain.weakest_confidence_grade,
        confidence_product=chain.confidence_product,
        published_at=chain.published_at,
        updated_at=chain.updated_at,
    )


def _public_options() -> tuple[Any, ...]:
    event = selectinload(Analysis.event)
    chains = event.selectinload(Event.chains)
    current = chains.selectinload(Chain.current_version)
    edges = current.selectinload(ChainVersion.edges)
    return (
        event.selectinload(Event.facts),
        current.selectinload(ChainVersion.nodes),
        edges.selectinload(CausalEdge.conditions),
        edges.selectinload(CausalEdge.evidence_links)
        .selectinload(EdgeEvidence.span)
        .selectinload(EvidenceSpan.document),
        edges.selectinload(CausalEdge.verification_specs).selectinload(VerificationSpec.runs),
    )


@router.get("", response_model=list[PublicAnalysisSummary])
async def list_public_analyses(
    category: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[PublicAnalysisSummary]:
    statement = (
        select(Analysis)
        .join(Analysis.event)
        .join(Event.chains)
        .where(
            Analysis.status == AnalysisStatus.PUBLISHED.value,
            Chain.status == ChainStatus.PUBLISHED.value,
            Chain.current_version_id.is_not(None),
        )
        .options(*_public_options())
        .order_by(Chain.published_at.desc(), Analysis.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if category:
        statement = statement.where(Event.category == category)
    analyses = list((await session.scalars(statement)).unique().all())
    return [
        _summary(analysis, chain)
        for analysis in analyses
        if analysis.event is not None and (chain := _published_chain(analysis.event)) is not None
    ]


@router.get("/{public_slug}", response_model=PublicAnalysisDetail)
async def get_public_analysis(
    public_slug: str,
    session: AsyncSession = Depends(get_session),
) -> PublicAnalysisDetail:
    analysis = await session.scalar(
        select(Analysis)
        .where(
            Analysis.public_slug == public_slug,
            Analysis.status == AnalysisStatus.PUBLISHED.value,
        )
        .options(*_public_options())
    )
    if analysis is None or analysis.event is None:
        raise NotFoundError("Published analysis not found.")
    chain = _published_chain(analysis.event)
    if chain is None or chain.current_version is None:
        raise NotFoundError("Published analysis not found.")

    version = chain.current_version
    edges = list(version.edges)
    evidence_by_edge = {
        str(edge.id): [PublicEdgeEvidenceRead.model_validate(link) for link in edge.evidence_links]
        for edge in edges
    }
    verification_by_edge = {
        str(edge.id): VerificationHistory(
            edge_id=edge.id,
            specs=[VerificationSpecRead.model_validate(spec) for spec in edge.verification_specs],
            runs=[
                VerificationRunRead.model_validate(run)
                for spec in edge.verification_specs
                for run in sorted(spec.runs, key=lambda item: item.created_at, reverse=True)
            ],
        )
        for edge in edges
    }
    return PublicAnalysisDetail(
        summary=_summary(analysis, chain),
        event=PublicEventRead.model_validate(analysis.event),
        graph=PublicChainGraph(
            chain=ChainSummary.model_validate(chain),
            version=PublicChainVersionRead.model_validate(version),
            nodes=[NodeRead.model_validate(node) for node in version.nodes],
            edges=[EdgeRead.model_validate(edge) for edge in edges],
        ),
        evidence_by_edge=evidence_by_edge,
        verification_by_edge=verification_by_edge,
    )
