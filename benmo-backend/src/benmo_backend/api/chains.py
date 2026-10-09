from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benmo_backend.dependencies import get_session
from benmo_backend.errors import NotFoundError
from benmo_backend.models import CausalEdge, Chain, ChainVersion
from benmo_backend.schemas import ChainGraph, ChainSummary, ChainVersionRead, EdgeRead, NodeRead

router = APIRouter(prefix="/chains", tags=["chains"])


@router.get("", response_model=list[ChainSummary])
async def list_chains(
    event_id: uuid.UUID | None = None,
    chain_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[Chain]:
    statement = select(Chain).order_by(Chain.created_at.desc())
    if event_id:
        statement = statement.where(Chain.event_id == event_id)
    if chain_status:
        statement = statement.where(Chain.status == chain_status)
    return list((await session.scalars(statement.offset(offset).limit(limit))).all())


@router.get("/{chain_id}", response_model=ChainSummary)
async def get_chain(chain_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Chain:
    chain = await session.get(Chain, chain_id)
    if chain is None:
        raise NotFoundError("Chain not found.", details={"id": str(chain_id)})
    return chain


@router.get("/{chain_id}/versions", response_model=list[ChainVersionRead])
async def list_chain_versions(
    chain_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> list[ChainVersion]:
    if await session.get(Chain, chain_id) is None:
        raise NotFoundError("Chain not found.", details={"id": str(chain_id)})
    return list(
        (
            await session.scalars(
                select(ChainVersion)
                .where(ChainVersion.chain_id == chain_id)
                .order_by(ChainVersion.version.desc())
            )
        ).all()
    )


@router.get("/{chain_id}/graph", response_model=ChainGraph)
async def get_chain_graph(
    chain_id: uuid.UUID,
    version: int | None = Query(default=None, ge=1),
    session: AsyncSession = Depends(get_session),
) -> ChainGraph:
    chain = await session.get(Chain, chain_id)
    if chain is None:
        raise NotFoundError("Chain not found.", details={"id": str(chain_id)})

    statement = (
        select(ChainVersion)
        .where(ChainVersion.chain_id == chain_id)
        .options(
            selectinload(ChainVersion.nodes),
            selectinload(ChainVersion.edges).selectinload(CausalEdge.conditions),
            selectinload(ChainVersion.edges).selectinload(CausalEdge.verification_specs),
        )
    )
    if version is not None:
        statement = statement.where(ChainVersion.version == version)
    elif chain.current_version_id is not None:
        statement = statement.where(ChainVersion.id == chain.current_version_id)
    else:
        statement = statement.order_by(ChainVersion.version.desc()).limit(1)
    chain_version = await session.scalar(statement)
    if chain_version is None:
        raise NotFoundError("Chain version not found.")

    return ChainGraph(
        chain=ChainSummary.model_validate(chain),
        version=ChainVersionRead.model_validate(chain_version),
        nodes=[NodeRead.model_validate(node) for node in chain_version.nodes],
        edges=[EdgeRead.model_validate(edge) for edge in chain_version.edges],
    )
