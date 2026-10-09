from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benmo_backend.dependencies import get_session
from benmo_backend.errors import NotFoundError
from benmo_backend.models import Event
from benmo_backend.schemas import EventRead

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventRead])
async def list_events(
    category: str | None = None,
    event_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[Event]:
    statement = select(Event).options(selectinload(Event.facts)).order_by(Event.created_at.desc())
    if category:
        statement = statement.where(Event.category == category)
    if event_status:
        statement = statement.where(Event.status == event_status)
    return list((await session.scalars(statement.offset(offset).limit(limit))).all())


@router.get("/{event_id}", response_model=EventRead)
async def get_event(event_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Event:
    event = await session.scalar(
        select(Event).where(Event.id == event_id).options(selectinload(Event.facts))
    )
    if event is None:
        raise NotFoundError("Event not found.", details={"id": str(event_id)})
    return event
