from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from benmo_backend.enums import WorkflowStatus
from benmo_backend.models import WorkflowRun
from benmo_backend.queueing.base import TaskMessage


class DatabaseTaskQueue:
    """Durable local fallback: workers claim queued workflow_runs with row locking."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def publish(self, message: TaskMessage) -> str:
        message_id = f"database-{message.task_id}"
        async with self._session_factory() as session:
            workflow = await session.get(WorkflowRun, message.task_id)
            if workflow is None:
                raise RuntimeError(f"Workflow run {message.task_id} does not exist")
            workflow.queue_message_id = message_id
            workflow.status = WorkflowStatus.QUEUED.value
            workflow.input_payload = message.model_dump(mode="json", exclude={"idempotency_key"})
            await session.commit()
        return message_id

    async def close(self) -> None:
        return None
