from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from benmo_backend.dependencies import get_queue, get_session
from benmo_backend.enums import AnalysisStatus
from benmo_backend.errors import NotFoundError
from benmo_backend.models import Analysis, AnalysisProgressEvent
from benmo_backend.queueing.base import TaskQueue
from benmo_backend.schemas import AnalysisAccepted, AnalysisCreate, AnalysisRead
from benmo_backend.services.analyses import create_analysis

router = APIRouter(prefix="/analyses", tags=["analyses"])
TERMINAL_STATUSES = {
    AnalysisStatus.PUBLISHED.value,
    AnalysisStatus.REJECTED.value,
    AnalysisStatus.FAILED.value,
}


@router.post("", response_model=AnalysisAccepted, status_code=status.HTTP_202_ACCEPTED)
async def submit_analysis(
    payload: AnalysisCreate,
    session: AsyncSession = Depends(get_session),
    queue: TaskQueue = Depends(get_queue),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AnalysisAccepted:
    return await create_analysis(session, queue, payload, idempotency_key)


@router.get("/{analysis_id}", response_model=AnalysisRead)
async def get_analysis(
    analysis_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Analysis:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise NotFoundError("Analysis not found.", details={"id": str(analysis_id)})
    return analysis


@router.get("/{analysis_id}/events", response_class=StreamingResponse)
async def stream_analysis_events(
    analysis_id: uuid.UUID,
    request: Request,
    after: int = Query(default=0, ge=0),
    follow: bool = Query(default=True),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    async with request.app.state.session_factory() as session:
        if await session.get(Analysis, analysis_id) is None:
            raise NotFoundError("Analysis not found.", details={"id": str(analysis_id)})

    if last_event_id and last_event_id.isdigit():
        after = max(after, int(last_event_id))

    async def generate() -> AsyncIterator[str]:
        cursor = after
        last_emission = time.monotonic()
        while True:
            if await request.is_disconnected():
                return
            async with request.app.state.session_factory() as session:
                events = (
                    await session.scalars(
                        select(AnalysisProgressEvent)
                        .where(
                            AnalysisProgressEvent.analysis_id == analysis_id,
                            AnalysisProgressEvent.sequence > cursor,
                        )
                        .order_by(AnalysisProgressEvent.sequence)
                    )
                ).all()
                analysis = await session.get(Analysis, analysis_id)

            for progress in events:
                cursor = progress.sequence
                data = {
                    "id": str(progress.id),
                    "analysis_id": str(progress.analysis_id),
                    "sequence": progress.sequence,
                    "message": progress.message,
                    "data": progress.data,
                    "created_at": progress.created_at.isoformat(),
                }
                yield (
                    f"id: {progress.sequence}\n"
                    f"event: {progress.event_type}\n"
                    f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                )
                last_emission = time.monotonic()

            terminal = analysis is None or analysis.status in TERMINAL_STATUSES
            if not follow or terminal:
                end_data = {"status": analysis.status if analysis else "gone"}
                yield f"event: end\ndata: {json.dumps(end_data)}\n\n"
                return
            if time.monotonic() - last_emission >= request.app.state.settings.sse_heartbeat_seconds:
                yield ": heartbeat\n\n"
                last_emission = time.monotonic()
            await asyncio.sleep(request.app.state.settings.sse_poll_interval_seconds)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
