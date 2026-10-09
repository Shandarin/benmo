from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from benmo_backend.config import Settings
from benmo_backend.main import create_app
from benmo_backend.queueing.memory import MemoryTaskQueue


@pytest.fixture
def worker_token() -> str:
    return "test-worker-token"


@pytest_asyncio.fixture
async def app(worker_token: str):  # type: ignore[no-untyped-def]
    settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        queue_backend="memory",
        auto_create_schema=True,
        admin_api_key="test-admin-key",
        backend_internal_token=worker_token,
        sse_poll_interval_seconds=0.01,
        sse_heartbeat_seconds=0.05,
    )
    queue = MemoryTaskQueue()
    application = create_app(settings, queue)
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value
