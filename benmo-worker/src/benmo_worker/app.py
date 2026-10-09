from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from benmo_worker.config import Settings
from benmo_worker.errors import PermanentTaskError
from benmo_worker.evidence import EvidenceProcessor
from benmo_worker.providers.registry import RuntimeDependencies, build_dependencies
from benmo_worker.publication import PublicationGate
from benmo_worker.queue import SqsDispatcher
from benmo_worker.schemas import (
    AnalysisRequest,
    DocumentFetchPayload,
    DocumentFilingPayload,
    GateAction,
    ManualReviewPayload,
    TaskMessage,
    TaskType,
    VerificationTaskPayload,
)
from benmo_worker.verification import DeterministicVerifier
from benmo_worker.workflows.analysis import AnalysisWorkflow
from benmo_worker.workflows.document import DocumentWorkflow
from benmo_worker.workflows.research import EdgeResearchWorkflow
from benmo_worker.workflows.verification import VerificationWorkflow


@dataclass(slots=True)
class WorkerApplication:
    settings: Settings
    dependencies: RuntimeDependencies
    analysis: AnalysisWorkflow
    documents: DocumentWorkflow
    verification: VerificationWorkflow
    dispatcher: SqsDispatcher | None = None

    async def handle_research(self, task: TaskMessage):  # type: ignore[no-untyped-def]
        if task.task_type != TaskType.ANALYSIS_RESEARCH or not isinstance(task.payload, AnalysisRequest):
            raise PermanentTaskError("research worker received a non-research payload")

        async def progress(stage: str, details: dict[str, object]) -> None:
            await self.dependencies.repository.progress(task, stage, dict(details))

        outcome = await self.analysis.run(task.payload, progress)
        await self.dependencies.repository.persist_analysis(outcome)
        if outcome.action == GateAction.REVIEW and self.dispatcher and self.settings.manual_review_queue_url:
            reasons = [
                reason
                for decision in outcome.chain_version.gate_decisions
                if decision.action == GateAction.REVIEW
                for reason in decision.reasons
            ]
            review = TaskMessage(
                task_type=TaskType.MANUAL_REVIEW,
                entity_id=outcome.analysis_id,
                source_version=outcome.chain_version.content_hash or "unhashed",
                workflow_version=self.settings.workflow_version,
                payload=ManualReviewPayload(
                    analysis_id=outcome.analysis_id,
                    edge_ids=outcome.review_edge_ids,
                    reasons=reasons or ["publication gate requested review"],
                ),
            )
            await self.dispatcher.send(self.settings.manual_review_queue_url, review)
        return outcome

    async def handle_document(self, task: TaskMessage):  # type: ignore[no-untyped-def]
        if task.task_type == TaskType.DOCUMENT_FETCH and isinstance(task.payload, DocumentFetchPayload):
            return await self.documents.fetch_and_verify(task.payload)
        if task.task_type == TaskType.DOCUMENT_FILING and isinstance(task.payload, DocumentFilingPayload):
            return await self.documents.fetch_filing(task.payload)
        raise PermanentTaskError("document worker received an incompatible payload")

    async def handle_verification(self, task: TaskMessage):  # type: ignore[no-untyped-def]
        if task.task_type != TaskType.VERIFICATION_RUN or not isinstance(task.payload, VerificationTaskPayload):
            raise PermanentTaskError("verification worker received an incompatible payload")
        return await self.verification.run(task.payload)


def build_application(settings: Settings, sqs_client: Any | None = None) -> WorkerApplication:
    dependencies = build_dependencies(settings)
    providers = dependencies.providers
    evidence = EvidenceProcessor(providers.documents, providers.entailment, dependencies.object_store)
    edge_research = EdgeResearchWorkflow(providers.research, evidence)
    analysis = AnalysisWorkflow(
        providers.reasoning,
        edge_research,
        PublicationGate(),
        settings.workflow_version,
    )
    documents = DocumentWorkflow(evidence, providers.sec)
    verification = VerificationWorkflow(providers.indicators, DeterministicVerifier())
    dispatcher = SqsDispatcher(sqs_client) if sqs_client is not None else None
    return WorkerApplication(settings, dependencies, analysis, documents, verification, dispatcher)
