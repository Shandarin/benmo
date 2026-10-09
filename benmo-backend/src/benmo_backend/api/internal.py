from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from benmo_backend.dependencies import get_session, require_worker
from benmo_backend.enums import AnalysisStatus, WorkflowStatus
from benmo_backend.errors import ConflictError, NotFoundError
from benmo_backend.internal_schemas import (
    AnalysisCompletionResponse,
    AnalysisFailRequest,
    AnalysisOutcomeIn,
    AnalysisProgressRequest,
    ModelRunIn,
    TaskClaimRequest,
    TaskClaimResponse,
    TaskCompleteRequest,
    TaskFailRequest,
    TaskProgressRequest,
)
from benmo_backend.models import (
    Analysis,
    AnalysisProgressEvent,
    IdempotencyRecord,
    ModelRun,
    WorkflowRun,
)
from benmo_backend.services.internal import next_progress_sequence, persist_analysis_outcome

router = APIRouter(
    prefix="/internal",
    tags=["internal-worker"],
    dependencies=[Depends(require_worker)],
    include_in_schema=False,
)


async def _task_record(session: AsyncSession, task_id: uuid.UUID) -> IdempotencyRecord:
    record = await session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.resource_type == "worker_task",
            IdempotencyRecord.resource_id == str(task_id),
        )
    )
    if record is None:
        raise NotFoundError("Worker task claim not found.", details={"task_id": str(task_id)})
    return record


@router.post("/worker/tasks/{task_id}/claim", response_model=TaskClaimResponse)
async def claim_task(
    task_id: uuid.UUID,
    payload: TaskClaimRequest,
    session: AsyncSession = Depends(get_session),
) -> TaskClaimResponse:
    workflow = await session.get(WorkflowRun, task_id)
    if workflow is None:
        raise NotFoundError("Workflow run not found.", details={"task_id": str(task_id)})
    if workflow.analysis_id and payload.entity_id != str(workflow.analysis_id):
        raise ConflictError("Worker task entity_id does not match its workflow run.")

    record = await session.scalar(
        select(IdempotencyRecord)
        .where(IdempotencyRecord.idempotency_key == payload.idempotency_key)
        .with_for_update()
    )
    if record is not None:
        if (
            record.task_type != payload.task_type
            or record.entity_id != payload.entity_id
            or record.workflow_version != payload.workflow_version
        ):
            raise ConflictError("Worker idempotency key collides with different task metadata.")
        if record.status in {"running", "completed", "permanent_failure"}:
            return TaskClaimResponse(
                claimed=False,
                previous_result=record.response_snapshot or None,
            )
        record.status = "running"
        record.resource_id = str(task_id)
        record.response_snapshot = {}
        workflow.status = WorkflowStatus.RUNNING.value
        workflow.started_at = workflow.started_at or datetime.now(UTC)
        await session.commit()
        return TaskClaimResponse(claimed=True)

    record = IdempotencyRecord(
        idempotency_key=payload.idempotency_key,
        task_type=payload.task_type,
        entity_id=payload.entity_id,
        source_version="worker-envelope",
        workflow_version=payload.workflow_version,
        request_hash=payload.idempotency_key,
        resource_type="worker_task",
        resource_id=str(task_id),
        status="running",
    )
    session.add(record)
    workflow.status = WorkflowStatus.RUNNING.value
    workflow.started_at = workflow.started_at or datetime.now(UTC)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.idempotency_key == payload.idempotency_key
            )
        )
        if existing is None:
            raise
        return TaskClaimResponse(claimed=False, previous_result=existing.response_snapshot or None)
    return TaskClaimResponse(claimed=True)


@router.post("/worker/tasks/{task_id}/progress", status_code=204)
async def task_progress(
    task_id: uuid.UUID,
    payload: TaskProgressRequest,
    session: AsyncSession = Depends(get_session),
) -> None:
    await _task_record(session, task_id)
    workflow = await session.get(WorkflowRun, task_id)
    if workflow is None:
        raise NotFoundError("Workflow run not found.", details={"task_id": str(task_id)})
    workflow.status = WorkflowStatus.RUNNING.value
    workflow.current_step = payload.stage
    if workflow.analysis_id:
        analysis = await session.get(Analysis, workflow.analysis_id)
        if analysis:
            analysis.status = AnalysisStatus.RUNNING.value
            analysis.current_stage = payload.stage
            if "progress_percent" in payload.details:
                analysis.progress_percent = max(
                    0, min(99, int(payload.details["progress_percent"]))
                )
            session.add(
                AnalysisProgressEvent(
                    analysis_id=analysis.id,
                    sequence=await next_progress_sequence(session, analysis.id),
                    event_type="analysis.progress",
                    message=str(payload.details.get("message") or payload.stage),
                    data={"stage": payload.stage, **payload.details},
                    created_at=payload.occurred_at or datetime.now(UTC),
                )
            )
    await session.commit()


@router.post("/worker/tasks/{task_id}/complete", status_code=204)
async def complete_task(
    task_id: uuid.UUID,
    payload: TaskCompleteRequest,
    session: AsyncSession = Depends(get_session),
) -> None:
    record = await _task_record(session, task_id)
    record.status = "completed"
    record.response_snapshot = payload.result
    workflow = await session.get(WorkflowRun, task_id)
    if workflow:
        workflow.status = WorkflowStatus.SUCCEEDED.value
        workflow.output_payload = payload.result
        workflow.completed_at = datetime.now(UTC)
    await session.commit()


@router.post("/worker/tasks/{task_id}/fail", status_code=204)
async def fail_task(
    task_id: uuid.UUID,
    payload: TaskFailRequest,
    session: AsyncSession = Depends(get_session),
) -> None:
    record = await _task_record(session, task_id)
    record.status = "retryable_failure" if payload.retryable else "permanent_failure"
    record.response_snapshot = {"error": payload.error, "retryable": payload.retryable}
    workflow = await session.get(WorkflowRun, task_id)
    if workflow:
        workflow.status = (
            WorkflowStatus.QUEUED.value if payload.retryable else WorkflowStatus.FAILED.value
        )
        workflow.error_message = payload.error
        workflow.completed_at = None if payload.retryable else datetime.now(UTC)
    await session.commit()


@router.post("/model-runs", status_code=204)
async def persist_model_run(
    payload: ModelRunIn,
    session: AsyncSession = Depends(get_session),
) -> None:
    existing = await session.get(ModelRun, payload.run_id)
    if existing is not None:
        if (
            existing.input_hash != payload.input_hash
            or existing.output_hash != payload.output_hash
            or existing.status != payload.status
        ):
            raise ConflictError("This immutable model run already has different content.")
        return
    session.add(
        ModelRun(
            id=payload.run_id,
            provider=payload.provider,
            model=payload.model,
            purpose=payload.purpose,
            prompt_template_version=payload.prompt_template_version,
            input_hash=payload.input_hash,
            output_hash=payload.output_hash,
            raw_response_storage_key=payload.raw_response_storage_key,
            structured_output=payload.structured_output,
            input_tokens=payload.input_tokens,
            output_tokens=payload.output_tokens,
            search_count=payload.search_count,
            latency_ms=payload.latency_ms,
            started_at=payload.started_at,
            completed_at=payload.completed_at,
            status=payload.status,
            error_message=payload.error_message,
        )
    )
    await session.commit()


@router.post("/analyses/{analysis_id}/progress", status_code=204)
async def analysis_progress(
    analysis_id: uuid.UUID,
    payload: AnalysisProgressRequest,
    session: AsyncSession = Depends(get_session),
) -> None:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise NotFoundError("Analysis not found.", details={"id": str(analysis_id)})
    if analysis.status in {
        AnalysisStatus.PUBLISHED.value,
        AnalysisStatus.REJECTED.value,
        AnalysisStatus.FAILED.value,
    }:
        raise ConflictError("A terminal analysis cannot receive progress updates.")
    analysis.status = AnalysisStatus.RUNNING.value
    analysis.current_stage = payload.stage
    analysis.progress_percent = payload.progress_percent
    if payload.workflow_run_id:
        workflow = await session.get(WorkflowRun, payload.workflow_run_id)
        if workflow and workflow.analysis_id == analysis.id:
            workflow.status = WorkflowStatus.RUNNING.value
            workflow.current_step = payload.stage
    session.add(
        AnalysisProgressEvent(
            analysis_id=analysis.id,
            sequence=await next_progress_sequence(session, analysis.id),
            event_type=payload.event_type,
            message=payload.message,
            data={
                "stage": payload.stage,
                "progress_percent": payload.progress_percent,
                **payload.data,
            },
        )
    )
    await session.commit()


@router.post("/analyses/{analysis_id}/complete", response_model=AnalysisCompletionResponse)
async def complete_analysis(
    analysis_id: uuid.UUID,
    payload: AnalysisOutcomeIn,
    session: AsyncSession = Depends(get_session),
) -> AnalysisCompletionResponse:
    return await persist_analysis_outcome(session, analysis_id, payload)


@router.post("/analyses/{analysis_id}/fail", status_code=204)
async def fail_analysis(
    analysis_id: uuid.UUID,
    payload: AnalysisFailRequest,
    session: AsyncSession = Depends(get_session),
) -> None:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise NotFoundError("Analysis not found.", details={"id": str(analysis_id)})
    analysis.status = AnalysisStatus.FAILED.value
    analysis.current_stage = payload.stage
    analysis.error_code = payload.error_code
    analysis.error_message = payload.error_message
    analysis.completed_at = datetime.now(UTC)
    if payload.workflow_run_id:
        workflow = await session.get(WorkflowRun, payload.workflow_run_id)
        if workflow and workflow.analysis_id == analysis.id:
            workflow.status = WorkflowStatus.FAILED.value
            workflow.error_message = payload.error_message
            workflow.completed_at = analysis.completed_at
    session.add(
        AnalysisProgressEvent(
            analysis_id=analysis.id,
            sequence=await next_progress_sequence(session, analysis.id),
            event_type="analysis.failed",
            message=payload.error_message,
            data={"error_code": payload.error_code, "stage": payload.stage},
        )
    )
    await session.commit()
