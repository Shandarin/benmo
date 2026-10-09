from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from typing import cast

from fastapi import Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from benmo_backend.config import Settings
from benmo_backend.errors import ForbiddenError
from benmo_backend.queueing.base import TaskQueue


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_queue(request: Request) -> TaskQueue:
    return cast(TaskQueue, request.app.state.task_queue)


def get_runtime_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def require_admin(
    request: Request,
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> str:
    expected: str = request.app.state.settings.admin_api_key
    if not x_admin_key or not hmac.compare_digest(x_admin_key, expected):
        raise ForbiddenError("A valid admin API key is required.")
    return x_admin_key


def require_worker(
    request: Request,
    x_worker_token: str | None = Header(default=None, alias="X-Benmo-Worker-Token"),
) -> str:
    expected: str = request.app.state.settings.backend_internal_token
    if not x_worker_token or not hmac.compare_digest(x_worker_token, expected):
        raise ForbiddenError("A valid worker token is required.")
    return x_worker_token
