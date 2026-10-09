from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benmo_backend.dependencies import get_session
from benmo_backend.errors import NotFoundError
from benmo_backend.models import CausalEdge, VerificationRun, VerificationSpec
from benmo_backend.schemas import VerificationHistory, VerificationRunRead, VerificationSpecRead

router = APIRouter(prefix="/verification", tags=["verification"])


@router.get("/specs/{spec_id}", response_model=VerificationSpecRead)
async def get_verification_spec(
    spec_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> VerificationSpec:
    spec = await session.get(VerificationSpec, spec_id)
    if spec is None:
        raise NotFoundError("Verification spec not found.", details={"id": str(spec_id)})
    return spec


@router.get("/runs/{run_id}", response_model=VerificationRunRead)
async def get_verification_run(
    run_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> VerificationRun:
    run = await session.get(VerificationRun, run_id)
    if run is None:
        raise NotFoundError("Verification run not found.", details={"id": str(run_id)})
    return run


@router.get("/edges/{edge_id}", response_model=VerificationHistory)
async def get_edge_verification_history(
    edge_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> VerificationHistory:
    edge = await session.get(CausalEdge, edge_id)
    if edge is None:
        raise NotFoundError("Causal edge not found.", details={"id": str(edge_id)})
    specs = list(
        (
            await session.scalars(
                select(VerificationSpec)
                .where(VerificationSpec.edge_id == edge_id)
                .options(selectinload(VerificationSpec.runs))
                .order_by(VerificationSpec.spec_version)
            )
        ).all()
    )
    runs = sorted(
        (run for spec in specs for run in spec.runs),
        key=lambda run: run.created_at,
        reverse=True,
    )
    return VerificationHistory(
        edge_id=edge_id,
        specs=[VerificationSpecRead.model_validate(spec) for spec in specs],
        runs=[VerificationRunRead.model_validate(run) for run in runs],
    )
