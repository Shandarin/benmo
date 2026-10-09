from __future__ import annotations

import asyncio
import uuid

from benmo_backend.queueing.base import TaskMessage


class MemoryTaskQueue:
    def __init__(self) -> None:
        self.messages: asyncio.Queue[TaskMessage] = asyncio.Queue()

    async def publish(self, message: TaskMessage) -> str:
        await self.messages.put(message)
        return f"memory-{uuid.uuid4()}"

    async def close(self) -> None:
        return None
