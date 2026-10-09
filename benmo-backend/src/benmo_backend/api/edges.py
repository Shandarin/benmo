from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benmo_backend.dependencies import get_session
from benmo_backend.errors import NotFoundError
from benmo_backend.models import CausalEdge
from benmo_backend.schemas import EdgeRead

router = APIRouter(prefix="/edges", tags=["edges"])


@router.get("/{edge_id}", response_model=EdgeRead)
async def get_edge(edge_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> CausalEdge:
    edge = await session.scalar(
        select(CausalEdge)
        .where(CausalEdge.id == edge_id)
        .options(
            selectinload(CausalEdge.conditions),
            selectinload(CausalEdge.verification_specs),
        )
    )
    if edge is None:
        raise NotFoundError("Causal edge not found.", details={"id": str(edge_id)})
    return edge
