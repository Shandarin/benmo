from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field, computed_field


class TaskMessage(BaseModel):
    """Canonical cross-service envelope mirrored by benmo-worker."""

    task_id: uuid.UUID
    task_type: str = "analysis.research"
    entity_id: str
    source_version: str = "user-input-v1"
    workflow_version: str = "analysis-v1"
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def idempotency_key(self) -> str:
        raw = ":".join((self.task_type, self.entity_id, self.source_version, self.workflow_version))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def wire_json(self) -> str:
        return self.model_dump_json(exclude={"idempotency_key"})


class TaskQueue(Protocol):
    async def publish(self, message: TaskMessage) -> str: ...

    async def close(self) -> None: ...
