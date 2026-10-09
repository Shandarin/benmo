from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benmo_backend.dependencies import get_session
from benmo_backend.errors import NotFoundError
from benmo_backend.models import EdgeEvidence, EvidenceDocument, EvidenceSpan
from benmo_backend.schemas import EdgeEvidenceRead, EvidenceDocumentRead, EvidenceSpanRead

router = APIRouter(tags=["evidence"])


@router.get("/evidence/{document_id}", response_model=EvidenceDocumentRead)
async def get_evidence_document(
    document_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> EvidenceDocument:
    document = await session.get(EvidenceDocument, document_id)
    if document is None:
        raise NotFoundError("Evidence document not found.", details={"id": str(document_id)})
    return document


@router.get("/evidence/{document_id}/spans", response_model=list[EvidenceSpanRead])
async def list_document_spans(
    document_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> list[EvidenceSpan]:
    if await session.get(EvidenceDocument, document_id) is None:
        raise NotFoundError("Evidence document not found.", details={"id": str(document_id)})
    return list(
        (
            await session.scalars(
                select(EvidenceSpan)
                .where(EvidenceSpan.document_id == document_id)
                .options(selectinload(EvidenceSpan.document))
                .order_by(EvidenceSpan.start_offset)
            )
        ).all()
    )


@router.get("/edges/{edge_id}/evidence", response_model=list[EdgeEvidenceRead])
async def list_edge_evidence(
    edge_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> list[EdgeEvidence]:
    links = (
        await session.scalars(
            select(EdgeEvidence)
            .where(EdgeEvidence.edge_id == edge_id)
            .options(selectinload(EdgeEvidence.span).selectinload(EvidenceSpan.document))
            .order_by(EdgeEvidence.created_at)
        )
    ).all()
    if not links:
        from benmo_backend.models import CausalEdge

        if await session.get(CausalEdge, edge_id) is None:
            raise NotFoundError("Causal edge not found.", details={"id": str(edge_id)})
    return list(links)
