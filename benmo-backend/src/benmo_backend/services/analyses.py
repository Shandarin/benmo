from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from benmo_backend.enums import AnalysisStatus, WorkflowStatus
from benmo_backend.errors import ConflictError, QueueUnavailableError
from benmo_backend.models import (
    Analysis,
    AnalysisProgressEvent,
    IdempotencyRecord,
    WorkflowRun,
)
from benmo_backend.queueing.base import TaskMessage, TaskQueue
from benmo_backend.schemas import AnalysisAccepted, AnalysisCreate

WORKFLOW_VERSION = "analysis-v1"
SOURCE_VERSION = "user-input-v1"


def _request_hash(request: AnalysisCreate) -> str:
    canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _accepted(analysis: Analysis) -> AnalysisAccepted:
    return AnalysisAccepted(
        analysis_id=analysis.id,
        status=AnalysisStatus(analysis.status),
        public_url=f"/analysis/{analysis.public_slug}",
    )


async def create_analysis(
    session: AsyncSession,
    queue: TaskQueue,
    request: AnalysisCreate,
    supplied_idempotency_key: str | None,
) -> AnalysisAccepted:
    request_hash = _request_hash(request)
    idempotency: IdempotencyRecord | None = None
    analysis: Analysis | None = None
    workflow: WorkflowRun | None = None

    if supplied_idempotency_key:
        idempotency = await session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.idempotency_key == supplied_idempotency_key
            )
        )
        if idempotency:
            if idempotency.request_hash != request_hash:
                raise ConflictError(
                    "The idempotency key was already used with a different request.",
                    details={"idempotency_key": supplied_idempotency_key},
                )
            analysis = await session.get(Analysis, uuid.UUID(idempotency.resource_id))
            if analysis is None:
                raise ConflictError("The idempotency record points to a missing analysis.")
            workflow = await session.scalar(
                select(WorkflowRun)
                .where(WorkflowRun.analysis_id == analysis.id)
                .order_by(WorkflowRun.created_at.desc())
                .limit(1)
            )
            if idempotency.status != WorkflowStatus.ENQUEUE_FAILED.value:
                return _accepted(analysis)

    if analysis is None:
        analysis_id = uuid.uuid4()
        public_slug = f"ana_{analysis_id.hex[:16]}"
        analysis = Analysis(
            id=analysis_id,
            input_text=request.input_text,
            input_context=request.context,
            status=AnalysisStatus.QUEUED.value,
            current_stage="queued",
            progress_percent=0,
            public_slug=public_slug,
        )
        workflow = WorkflowRun(
            analysis=analysis,
            workflow_type="analysis",
            workflow_version=WORKFLOW_VERSION,
            status=WorkflowStatus.QUEUED.value,
            current_step="normalize_event",
            input_payload={
                "analysis_id": str(analysis_id),
                "input_text": request.input_text,
                "context": request.context,
            },
        )
        session.add_all(
            [
                analysis,
                workflow,
                AnalysisProgressEvent(
                    analysis=analysis,
                    sequence=1,
                    event_type="analysis.queued",
                    message="Analysis request accepted and queued.",
                    data={"stage": "queued", "progress_percent": 0},
                ),
            ]
        )
        await session.flush()

        effective_key = supplied_idempotency_key or (
            f"analysis_requested:{analysis.id}:{SOURCE_VERSION}:{WORKFLOW_VERSION}"
        )
        idempotency = IdempotencyRecord(
            idempotency_key=effective_key,
            task_type="analysis_requested",
            entity_id=str(analysis.id),
            source_version=SOURCE_VERSION,
            workflow_version=WORKFLOW_VERSION,
            request_hash=request_hash,
            resource_type="analysis",
            resource_id=str(analysis.id),
            status="accepted",
            response_snapshot=_accepted(analysis).model_dump(mode="json"),
        )
        session.add(idempotency)
        await session.commit()

    assert analysis is not None
    assert workflow is not None
    assert idempotency is not None
    message = TaskMessage(
        task_id=workflow.id,
        task_type="analysis.research",
        entity_id=str(analysis.id),
        source_version=SOURCE_VERSION,
        workflow_version=WORKFLOW_VERSION,
        payload={
            "analysis_id": str(analysis.id),
            "query": analysis.input_text,
            "occurred_at": analysis.input_context.get("occurred_at"),
            "locale": analysis.input_context.get("locale", "zh-CN"),
        },
    )

    try:
        queue_message_id = await queue.publish(message)
    except Exception as exc:
        analysis.status = AnalysisStatus.FAILED.value
        analysis.current_stage = "enqueue_failed"
        analysis.error_code = "queue_unavailable"
        analysis.error_message = str(exc)
        workflow.status = WorkflowStatus.ENQUEUE_FAILED.value
        workflow.error_message = str(exc)
        idempotency.status = WorkflowStatus.ENQUEUE_FAILED.value
        session.add(
            AnalysisProgressEvent(
                analysis_id=analysis.id,
                sequence=2,
                event_type="analysis.enqueue_failed",
                message="The analysis queue is temporarily unavailable.",
                data={"retryable": True},
            )
        )
        await session.commit()
        raise QueueUnavailableError(
            "The analysis was recorded but could not be queued; retry with the same "
            "idempotency key."
        ) from exc

    workflow.queue_message_id = queue_message_id
    workflow.status = WorkflowStatus.QUEUED.value
    workflow.error_message = None
    analysis.status = AnalysisStatus.QUEUED.value
    analysis.current_stage = "queued"
    analysis.error_code = None
    analysis.error_message = None
    idempotency.status = "accepted"
    await session.commit()
    return _accepted(analysis)
