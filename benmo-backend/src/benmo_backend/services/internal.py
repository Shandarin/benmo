from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from benmo_backend.domains.confidence import EdgeAggregateInput, aggregate_chain
from benmo_backend.enums import (
    AnalysisStatus,
    ChainStatus,
    ConfidenceGrade,
    OutcomeStatus,
    ReviewDecision,
    WorkflowStatus,
)
from benmo_backend.errors import ConflictError, NotFoundError
from benmo_backend.internal_schemas import AnalysisCompletionResponse, AnalysisOutcomeIn
from benmo_backend.models import (
    Analysis,
    AnalysisProgressEvent,
    AuditLog,
    CausalEdge,
    Chain,
    ChainVersion,
    Company,
    Condition,
    EdgeEvidence,
    Event,
    EventFact,
    EvidenceDocument,
    EvidenceSpan,
    PublicationReview,
    TickerExposure,
    VerificationSpec,
    WorkflowRun,
)

EXTERNAL_ID_NAMESPACE = uuid.UUID("f052a96f-e09e-4ea8-b043-ffab7c095fd4")
GRADE_SCORE = {
    ConfidenceGrade.A: Decimal("90.00"),
    ConfidenceGrade.B: Decimal("77.00"),
    ConfidenceGrade.C: Decimal("62.00"),
    ConfidenceGrade.INSUFFICIENT: Decimal("0.00"),
}


def external_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.uuid5(EXTERNAL_ID_NAMESPACE, value)


def canonical_hash(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def next_progress_sequence(session: AsyncSession, analysis_id: uuid.UUID) -> int:
    current = await session.scalar(
        select(func.max(AnalysisProgressEvent.sequence)).where(
            AnalysisProgressEvent.analysis_id == analysis_id
        )
    )
    return int(current or 0) + 1


def _slug(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return (clean or f"chain-{external_uuid(value).hex[:12]}")[:100]


def _version_hash(outcome: AnalysisOutcomeIn) -> str:
    chain_payload = outcome.chain_version.model_dump(mode="json", exclude={"content_hash"})
    return canonical_hash(chain_payload)


def _spec_hash(spec: Any) -> str:
    return canonical_hash(spec.model_dump(mode="json", exclude={"spec_hash"}))


async def persist_analysis_outcome(
    session: AsyncSession,
    analysis_id: uuid.UUID,
    outcome: AnalysisOutcomeIn,
) -> AnalysisCompletionResponse:
    if outcome.analysis_id != str(analysis_id):
        raise ConflictError("Outcome analysis_id does not match the request path.")
    if outcome.chain_version.analysis_id != outcome.analysis_id:
        raise ConflictError("Chain version analysis_id does not match the outcome.")
    if _version_hash(outcome) != outcome.chain_version.content_hash:
        raise ConflictError("Chain version content_hash does not match its canonical payload.")
    for spec in outcome.chain_version.verification_specs:
        if spec.spec_hash and _spec_hash(spec) != spec.spec_hash:
            raise ConflictError(
                "Verification spec hash does not match its canonical payload.",
                details={"spec_id": spec.spec_id},
            )

    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise NotFoundError("Analysis not found.", details={"id": str(analysis_id)})

    chain_id = external_uuid(outcome.chain_version.chain_id)
    chain_version_id = external_uuid(
        f"{outcome.chain_version.chain_id}:v{outcome.chain_version.version}"
    )
    existing = await session.get(ChainVersion, chain_version_id)
    if existing is not None:
        existing_hash = existing.snapshot.get("content_hash")
        if existing_hash != outcome.chain_version.content_hash:
            raise ConflictError("This immutable chain version already has different content.")
        chain = await session.get(Chain, chain_id)
        assert chain is not None
        return AnalysisCompletionResponse(
            analysis_id=analysis_id,
            chain_id=chain.id,
            chain_version_id=existing.id,
            status=analysis.status,
            idempotent_replay=True,
        )

    normalized = outcome.chain_version.event
    event = Event(
        title=normalized.claimed_event,
        description="\n".join(normalized.unverified_claims) or normalized.claimed_event,
        status="verified" if normalized.observed_facts else "candidate",
        source_input={
            "analysis_id": outcome.analysis_id,
            "normalized_at": normalized.normalized_at.isoformat(),
            "unverified_claims": normalized.unverified_claims,
        },
    )
    session.add(event)
    await session.flush()
    analysis.event_id = event.id
    for fact in normalized.observed_facts:
        details: dict[str, Any] = {
            "change_pct": str(fact.change_pct) if fact.change_pct is not None else None,
            "source_hint": fact.source_hint,
        }
        session.add(
            EventFact(
                event_id=event.id,
                subject=fact.subject,
                metric_code=fact.metric,
                observed_value=fact.value,
                unit=fact.unit,
                period=fact.period,
                fact_status=fact.status,
                as_of=fact.observed_at,
                details=details,
            )
        )

    action_status = {
        "publish": ChainStatus.PUBLISHED.value,
        "human_review": ChainStatus.REVIEW_REQUIRED.value,
        "reject": ChainStatus.DRAFT.value,
    }
    chain = Chain(
        id=chain_id,
        event_id=event.id,
        title=normalized.claimed_event,
        slug=_slug(outcome.chain_version.chain_id),
        status=action_status[outcome.action],
    )
    session.add(chain)
    await session.flush()
    version_status = {
        "publish": "published",
        "human_review": "review_required",
        "reject": "rejected",
    }[outcome.action]
    now = datetime.now(UTC)
    version = ChainVersion(
        id=chain_version_id,
        chain_id=chain.id,
        version=outcome.chain_version.version,
        status=version_status,
        snapshot=outcome.chain_version.model_dump(mode="json"),
        created_at=outcome.chain_version.created_at,
        published_at=now if outcome.action == "publish" else None,
    )
    session.add(version)
    await session.flush()

    gate_by_external_id = {item.edge_id: item for item in outcome.chain_version.gate_decisions}
    edge_by_external_id: dict[str, CausalEdge] = {}
    node_by_identity: dict[tuple[str, str], uuid.UUID] = {}

    async def node_id(label: str, node_type: str) -> uuid.UUID:
        identity = (label, node_type)
        if identity not in node_by_identity:
            from benmo_backend.models import Node

            value = external_uuid(f"{chain_version_id}:node:{node_type}:{label}")
            node_by_identity[identity] = value
            session.add(
                Node(
                    id=value,
                    chain_version_id=version.id,
                    key=f"node_{len(node_by_identity)}",
                    node_type=node_type,
                    label=label,
                    attributes={"derived_from_worker_edges": True},
                )
            )
        return node_by_identity[identity]

    rejected = set(outcome.rejected_edge_ids)
    for researched in outcome.chain_version.edges:
        item = researched.edge
        if item.edge_id in rejected:
            continue
        gate = gate_by_external_id.get(item.edge_id)
        grade = ConfidenceGrade(gate.confidence_grade if gate else "Insufficient")
        edge = CausalEdge(
            id=external_uuid(item.edge_id),
            chain_version_id=version.id,
            from_node_id=await node_id(item.from_node, item.from_node_type),
            to_node_id=await node_id(item.to_node, item.to_node_type),
            relation_type=item.relation_type,
            direction=item.direction,
            mechanism=item.mechanism,
            evidence_status=gate.evidence_status if gate else "unsupported",
            outcome_status=OutcomeStatus.PENDING.value,
            confidence_grade=grade.value,
            confidence_score=GRADE_SCORE[grade],
            confidence_breakdown={
                "source": "worker_publication_gate_v1",
                "reasons": gate.reasons if gate else [],
                "direct_support_count": gate.direct_support_count if gate else 0,
                "primary_source_count": gate.primary_source_count if gate else 0,
                "independent_secondary_count": gate.independent_secondary_count if gate else 0,
            },
            is_critical=item.edge_id in set(outcome.review_edge_ids),
            created_by_model_run_id=item.created_by_model_run_id,
        )
        session.add(edge)
        edge_by_external_id[item.edge_id] = edge
        for index, statement in enumerate(item.conditions):
            session.add(
                Condition(edge=edge, kind="condition", statement=statement, sort_order=index)
            )
        for index, statement in enumerate(item.invalidation_conditions):
            session.add(
                Condition(edge=edge, kind="invalidation", statement=statement, sort_order=index)
            )

        all_evidence = [("support", value) for value in researched.supporting] + [
            ("adversarial", value) for value in researched.adversarial
        ]
        for role, evaluated in all_evidence:
            span_in = evaluated.span
            document_id = external_uuid(span_in.source_id)
            document = await session.get(EvidenceDocument, document_id)
            if document is None:
                document = EvidenceDocument(
                    id=document_id,
                    source_url=span_in.source_url,
                    source_type=span_in.source_type,
                    source_tier=span_in.tier,
                    publisher=span_in.publisher,
                    published_at=span_in.published_at,
                    retrieved_at=span_in.retrieved_at,
                    content_hash=span_in.snapshot_hash,
                    storage_key=span_in.snapshot_object_key,
                    content_type=span_in.snapshot_content_type or "text/plain",
                    is_accessible=True,
                    source_metadata={"worker_source_id": span_in.source_id},
                )
                session.add(document)
                await session.flush()
            span_id = external_uuid(span_in.evidence_id)
            span = await session.get(EvidenceSpan, span_id)
            if span is None:
                span = EvidenceSpan(
                    id=span_id,
                    document_id=document.id,
                    quoted_span=span_in.quoted_span,
                    start_offset=span_in.start_offset,
                    end_offset=span_in.end_offset,
                    content_hash=span_in.quote_hash,
                    supported_claim=span_in.supported_claim,
                    support_level=span_in.support_level,
                    limitations=span_in.limitations,
                    quote_verified=True,
                    verified_at=now,
                )
                session.add(span)
                await session.flush()
            contradiction_level = "none"
            if role == "adversarial":
                contradiction_level = gate.contradiction_level if gate else "minor"
            session.add(
                EdgeEvidence(
                    edge_id=edge.id,
                    evidence_span_id=span.id,
                    role=role,
                    entailment_status=evaluated.entailment.label,
                    is_direct=(
                        role == "support" and evaluated.entailment.label == "directly_supports"
                    ),
                    independent_source_key=span_in.independent_source_key,
                    contradiction_level=contradiction_level,
                )
            )

        if item.ticker:
            company_id = external_uuid(f"ticker:{item.ticker}")
            company = await session.get(Company, company_id)
            if company is None:
                company = Company(id=company_id, legal_name=item.ticker, ticker=item.ticker)
                session.add(company)
            evidence_refs = [
                {"evidence_id": entry.span.evidence_id, "claim": entry.span.supported_claim}
                for entry in researched.supporting
                if entry.entailment.label == "directly_supports"
            ]
            session.add(
                TickerExposure(
                    edge_id=edge.id,
                    company_id=company_id,
                    exposure_type=item.relation_type,
                    exposure_direction=item.direction,
                    materiality="unknown",
                    time_scale=item.time_scale,
                    exposure_evidence=evidence_refs,
                    offsetting_factors=item.invalidation_conditions,
                    is_public=bool(evidence_refs) and not bool(gate and gate.ticker_removed),
                )
            )

    for spec in outcome.chain_version.verification_specs:
        spec_edge = edge_by_external_id.get(spec.edge_id)
        if spec_edge is None:
            continue
        session.add(
            VerificationSpec(
                id=external_uuid(spec.spec_id),
                edge_id=spec_edge.id,
                metric_code=spec.metric_code,
                source_adapter=spec.source_adapter,
                expected_direction=spec.expected_direction,
                threshold={
                    "value": str(spec.threshold),
                    "minimum_observations": spec.minimum_observations,
                },
                baseline_rule={
                    "rule": spec.baseline_rule,
                    "value": str(spec.baseline_value) if spec.baseline_value is not None else None,
                },
                observation_window=spec.observation_window.model_dump(mode="json"),
                comparator_expression=spec.comparator,
                spec_version=spec.spec_version,
                locked_at=spec.locked_at,
            )
        )

    aggregate = aggregate_chain(
        EdgeAggregateInput(
            score=edge.confidence_score,
            grade=ConfidenceGrade(edge.confidence_grade),
            outcome_status=OutcomeStatus(edge.outcome_status),
            is_critical=edge.is_critical,
        )
        for edge in edge_by_external_id.values()
    )
    chain.weakest_confidence_grade = aggregate.weakest_grade.value
    chain.confidence_product = aggregate.confidence_product
    if outcome.action == "publish":
        chain.current_version_id = version.id
        chain.published_at = now
    elif outcome.action == "human_review":
        session.add(
            PublicationReview(
                chain_version_id=version.id,
                requested_reason="; ".join(
                    reason
                    for decision in outcome.chain_version.gate_decisions
                    if decision.action == "human_review"
                    for reason in decision.reasons
                )
                or "Worker publication gate requires human review.",
                gate_result={
                    "decisions": [
                        item.model_dump(mode="json")
                        for item in outcome.chain_version.gate_decisions
                    ]
                },
                status=ReviewDecision.PENDING.value,
            )
        )

    analysis.status = {
        "publish": AnalysisStatus.PUBLISHED.value,
        "human_review": AnalysisStatus.REVIEW_REQUIRED.value,
        "reject": AnalysisStatus.REJECTED.value,
    }[outcome.action]
    analysis.current_stage = "completed"
    analysis.progress_percent = 100
    analysis.completed_at = now
    workflows = (
        await session.scalars(select(WorkflowRun).where(WorkflowRun.analysis_id == analysis.id))
    ).all()
    for workflow in workflows:
        workflow.status = WorkflowStatus.SUCCEEDED.value
        workflow.current_step = "completed"
        workflow.output_payload = {
            "chain_id": str(chain.id),
            "chain_version_id": str(version.id),
            "content_hash": outcome.chain_version.content_hash,
        }
        workflow.completed_at = now

    session.add(
        AnalysisProgressEvent(
            analysis_id=analysis.id,
            sequence=await next_progress_sequence(session, analysis.id),
            event_type="analysis.completed",
            message="The causal chain analysis is complete.",
            data={
                "action": outcome.action,
                "chain_id": str(chain.id),
                "chain_version_id": str(version.id),
            },
        )
    )
    session.add(
        AuditLog(
            actor_type="worker",
            action="analysis.outcome_persisted",
            resource_type="analysis",
            resource_id=str(analysis.id),
            after_state={
                "status": analysis.status,
                "chain_version_id": str(version.id),
                "content_hash": outcome.chain_version.content_hash,
            },
        )
    )
    await session.commit()
    return AnalysisCompletionResponse(
        analysis_id=analysis.id,
        chain_id=chain.id,
        chain_version_id=version.id,
        status=analysis.status,
    )
