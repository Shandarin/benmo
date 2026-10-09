from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from benmo_backend.dependencies import get_session, require_admin
from benmo_backend.enums import AnalysisStatus, ChainStatus, PublicationDecision, ReviewDecision
from benmo_backend.errors import ConflictError, NotFoundError
from benmo_backend.models import (
    Analysis,
    AnalysisProgressEvent,
    AuditLog,
    Chain,
    ChainVersion,
    PublicationReview,
    TickerExposure,
)
from benmo_backend.schemas import (
    GateReasonSchema,
    PublicationGateResponse,
    PublicationReviewRead,
    ReviewDecisionRequest,
)
from benmo_backend.services.publication import evaluate_chain_version

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


async def _sync_analysis_publication_status(
    session: AsyncSession,
    chain: Chain,
    status: AnalysisStatus,
    now: datetime,
    message: str,
) -> None:
    analysis = await session.scalar(
        select(Analysis)
        .where(Analysis.event_id == chain.event_id)
        .order_by(Analysis.created_at.desc())
        .limit(1)
    )
    if analysis is None or analysis.status == status.value:
        return
    analysis.status = status.value
    analysis.current_stage = "completed"
    analysis.progress_percent = 100
    analysis.completed_at = analysis.completed_at or now
    sequence = (
        await session.scalar(
            select(func.max(AnalysisProgressEvent.sequence)).where(
                AnalysisProgressEvent.analysis_id == analysis.id
            )
        )
        or 0
    ) + 1
    session.add(
        AnalysisProgressEvent(
            analysis_id=analysis.id,
            sequence=sequence,
            event_type="analysis.review_decided",
            message=message,
            data={
                "status": status.value,
                "progress_percent": 100,
                "public_url": (
                    f"/analysis/{analysis.public_slug}"
                    if status == AnalysisStatus.PUBLISHED
                    else None
                ),
            },
        )
    )


@router.get("/reviews", response_model=list[PublicationReviewRead])
async def list_reviews(
    review_status: ReviewDecision = Query(default=ReviewDecision.PENDING, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[PublicationReview]:
    return list(
        (
            await session.scalars(
                select(PublicationReview)
                .where(PublicationReview.status == review_status.value)
                .order_by(PublicationReview.created_at)
                .limit(limit)
            )
        ).all()
    )


@router.post(
    "/chain-versions/{chain_version_id}/publication-gate",
    response_model=PublicationGateResponse,
)
async def run_publication_gate(
    chain_version_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> PublicationGateResponse:
    result = await evaluate_chain_version(session, chain_version_id)
    version = await session.get(ChainVersion, chain_version_id)
    assert version is not None
    chain = await session.get(Chain, version.chain_id)
    assert chain is not None

    if result.excluded_ticker_exposure_ids:
        exposures = (
            await session.scalars(
                select(TickerExposure).where(
                    TickerExposure.id.in_(result.excluded_ticker_exposure_ids)
                )
            )
        ).all()
        for exposure in exposures:
            exposure.is_public = False

    gate_snapshot = {
        "decision": result.decision.value,
        "reasons": [
            {
                "code": item.code,
                "message": item.message,
                "edge_id": str(item.edge_id) if item.edge_id else None,
            }
            for item in result.reasons
        ],
        "excluded_ticker_exposure_ids": [str(item) for item in result.excluded_ticker_exposure_ids],
        "evaluated_edge_count": result.evaluated_edge_count,
    }
    now = datetime.now(UTC)
    if result.decision == PublicationDecision.PUBLISH:
        version.status = "published"
        version.published_at = now
        chain.current_version_id = version.id
        chain.status = ChainStatus.PUBLISHED.value
        chain.published_at = now
        await _sync_analysis_publication_status(
            session,
            chain,
            AnalysisStatus.PUBLISHED,
            now,
            "The analysis passed the publication gate.",
        )
    elif result.decision == PublicationDecision.REVIEW:
        existing = await session.scalar(
            select(PublicationReview).where(
                PublicationReview.chain_version_id == version.id,
                PublicationReview.status == ReviewDecision.PENDING.value,
            )
        )
        if existing is None:
            session.add(
                PublicationReview(
                    chain_version_id=version.id,
                    requested_reason="Material contradictory evidence requires human review.",
                    gate_result=gate_snapshot,
                )
            )
        version.status = "review_required"
        chain.status = ChainStatus.REVIEW_REQUIRED.value
        await _sync_analysis_publication_status(
            session,
            chain,
            AnalysisStatus.REVIEW_REQUIRED,
            now,
            "The analysis requires human review before publication.",
        )
    else:
        version.status = "rejected"
        chain.status = ChainStatus.DRAFT.value
        await _sync_analysis_publication_status(
            session,
            chain,
            AnalysisStatus.REJECTED,
            now,
            "The analysis did not pass the publication gate.",
        )

    session.add(
        AuditLog(
            actor_type="admin",
            action="publication_gate.evaluated",
            resource_type="chain_version",
            resource_id=str(version.id),
            after_state=gate_snapshot,
        )
    )
    await session.commit()
    return PublicationGateResponse(
        decision=result.decision,
        reasons=[
            GateReasonSchema(code=item.code, message=item.message, edge_id=item.edge_id)
            for item in result.reasons
        ],
        excluded_ticker_exposure_ids=list(result.excluded_ticker_exposure_ids),
        evaluated_edge_count=result.evaluated_edge_count,
    )


@router.post("/reviews/{review_id}/decision", response_model=PublicationReviewRead)
async def decide_review(
    review_id: uuid.UUID,
    payload: ReviewDecisionRequest,
    session: AsyncSession = Depends(get_session),
) -> PublicationReview:
    review = await session.get(PublicationReview, review_id)
    if review is None:
        raise NotFoundError("Publication review not found.", details={"id": str(review_id)})
    if review.status != ReviewDecision.PENDING.value:
        raise ConflictError("This publication review has already been decided.")

    now = datetime.now(UTC)
    review.status = payload.decision.value
    review.reviewer_id = payload.reviewer_id
    review.decision_notes = payload.notes
    review.decided_at = now
    version = await session.get(ChainVersion, review.chain_version_id)
    assert version is not None
    chain = await session.get(Chain, version.chain_id)
    assert chain is not None

    if payload.decision == ReviewDecision.APPROVED:
        version.status = "published"
        version.published_at = now
        chain.current_version_id = version.id
        chain.status = ChainStatus.PUBLISHED.value
        chain.published_at = now
        await _sync_analysis_publication_status(
            session,
            chain,
            AnalysisStatus.PUBLISHED,
            now,
            "The analysis was approved and published after review.",
        )
    else:
        version.status = "rejected"
        chain.status = ChainStatus.DRAFT.value
        await _sync_analysis_publication_status(
            session,
            chain,
            AnalysisStatus.REJECTED,
            now,
            "The analysis was rejected after review.",
        )

    session.add(
        AuditLog(
            actor_type="reviewer",
            actor_id=payload.reviewer_id,
            action=f"publication_review.{payload.decision.value}",
            resource_type="publication_review",
            resource_id=str(review.id),
            before_state={"status": ReviewDecision.PENDING.value},
            after_state={"status": payload.decision.value, "notes": payload.notes},
        )
    )
    await session.commit()
    await session.refresh(review)
    return review
