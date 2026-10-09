from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from benmo_backend.enums import (
    AnalysisStatus,
    ChainStatus,
    ConfidenceGrade,
    EvidenceStatus,
    OutcomeStatus,
    PublicationDecision,
    ReviewDecision,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class AnalysisCreate(BaseModel):
    input_text: str = Field(min_length=10, max_length=10_000)
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input_text")
    @classmethod
    def strip_input(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("input_text must not be blank")
        return value


class AnalysisAccepted(BaseModel):
    analysis_id: uuid.UUID
    status: AnalysisStatus
    public_url: str


class AnalysisRead(ORMModel):
    id: uuid.UUID
    event_id: uuid.UUID | None
    input_text: str
    input_context: dict[str, Any]
    status: AnalysisStatus
    current_stage: str
    progress_percent: int
    public_slug: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class AnalysisProgressEventRead(ORMModel):
    id: uuid.UUID
    analysis_id: uuid.UUID
    sequence: int
    event_type: str
    message: str
    data: dict[str, Any]
    created_at: datetime


class EventFactRead(ORMModel):
    id: uuid.UUID
    subject: str
    metric_code: str | None
    observed_value: Decimal | None
    unit: str | None
    period: str | None
    fact_status: str
    source_document_id: uuid.UUID | None
    as_of: datetime | None
    details: dict[str, Any]


class EventRead(ORMModel):
    id: uuid.UUID
    title: str
    description: str
    category: str | None
    occurred_at: datetime | None
    status: str
    source_input: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    facts: list[EventFactRead] = Field(default_factory=list)


class PublicEventRead(ORMModel):
    id: uuid.UUID
    title: str
    description: str
    category: str | None
    occurred_at: datetime | None
    status: str
    created_at: datetime
    updated_at: datetime
    facts: list[EventFactRead] = Field(default_factory=list)


class NodeRead(ORMModel):
    id: uuid.UUID
    chain_version_id: uuid.UUID
    key: str
    node_type: str
    label: str
    metric_code: str | None
    entity_ref: str | None
    attributes: dict[str, Any]


class ConditionRead(ORMModel):
    id: uuid.UUID
    kind: str
    statement: str
    sort_order: int


class VerificationSpecRead(ORMModel):
    id: uuid.UUID
    edge_id: uuid.UUID
    metric_code: str
    source_adapter: str
    expected_direction: str
    threshold: dict[str, Any]
    baseline_rule: dict[str, Any]
    observation_window: dict[str, Any]
    comparator_expression: str
    spec_version: int
    supersedes_id: uuid.UUID | None
    locked_at: datetime
    created_at: datetime


class EdgeSummary(ORMModel):
    id: uuid.UUID
    chain_version_id: uuid.UUID
    from_node_id: uuid.UUID
    to_node_id: uuid.UUID
    relation_type: str
    direction: str
    mechanism: str
    evidence_status: EvidenceStatus
    outcome_status: OutcomeStatus
    confidence_grade: ConfidenceGrade
    confidence_score: Decimal | None
    confidence_breakdown: dict[str, Any]
    is_critical: bool


class EdgeRead(EdgeSummary):
    conditions: list[ConditionRead] = Field(default_factory=list)
    verification_specs: list[VerificationSpecRead] = Field(default_factory=list)


class ChainSummary(ORMModel):
    id: uuid.UUID
    event_id: uuid.UUID
    title: str
    slug: str
    status: ChainStatus
    current_version_id: uuid.UUID | None
    weakest_confidence_grade: ConfidenceGrade
    confidence_product: Decimal | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChainVersionRead(ORMModel):
    id: uuid.UUID
    chain_id: uuid.UUID
    version: int
    status: str
    snapshot: dict[str, Any]
    created_by_model_run_id: uuid.UUID | None
    created_at: datetime
    published_at: datetime | None


class PublicChainVersionRead(ORMModel):
    id: uuid.UUID
    chain_id: uuid.UUID
    version: int
    status: str
    created_at: datetime
    published_at: datetime | None


class ChainGraph(BaseModel):
    chain: ChainSummary
    version: ChainVersionRead
    nodes: list[NodeRead]
    edges: list[EdgeRead]


class PublicChainGraph(BaseModel):
    chain: ChainSummary
    version: PublicChainVersionRead
    nodes: list[NodeRead]
    edges: list[EdgeRead]


class EvidenceDocumentRead(ORMModel):
    id: uuid.UUID
    source_url: str
    canonical_url: str | None
    source_type: str
    source_tier: Literal["A", "B", "C", "D"]
    publisher: str | None
    published_at: datetime | None
    retrieved_at: datetime
    content_hash: str
    storage_key: str | None
    content_type: str | None
    is_accessible: bool
    source_metadata: dict[str, Any]


class EvidenceSpanRead(ORMModel):
    id: uuid.UUID
    document_id: uuid.UUID
    quoted_span: str
    start_offset: int
    end_offset: int
    content_hash: str
    supported_claim: str
    support_level: str
    limitations: list[str]
    quote_verified: bool
    verified_at: datetime | None
    document: EvidenceDocumentRead


class EdgeEvidenceRead(ORMModel):
    id: uuid.UUID
    edge_id: uuid.UUID
    role: str
    entailment_status: str
    is_direct: bool
    independent_source_key: str | None
    contradiction_level: str
    span: EvidenceSpanRead


class PublicEvidenceDocumentRead(ORMModel):
    id: uuid.UUID
    source_url: str
    canonical_url: str | None
    source_type: str
    source_tier: Literal["A", "B", "C", "D"]
    publisher: str | None
    published_at: datetime | None
    retrieved_at: datetime
    content_type: str | None
    is_accessible: bool


class PublicEvidenceSpanRead(ORMModel):
    id: uuid.UUID
    document_id: uuid.UUID
    quoted_span: str
    supported_claim: str
    support_level: str
    limitations: list[str]
    quote_verified: bool
    verified_at: datetime | None
    document: PublicEvidenceDocumentRead


class PublicEdgeEvidenceRead(ORMModel):
    id: uuid.UUID
    edge_id: uuid.UUID
    role: str
    entailment_status: str
    is_direct: bool
    independent_source_key: str | None
    contradiction_level: str
    span: PublicEvidenceSpanRead


class VerificationRunRead(ORMModel):
    id: uuid.UUID
    verification_spec_id: uuid.UUID
    scheduled_for: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    outcome_status: OutcomeStatus
    observed_value: Decimal | None
    baseline_value: Decimal | None
    change_pct: Decimal | None
    threshold_pct: Decimal | None
    evaluated_by: str | None
    result: dict[str, Any]
    error_message: str | None
    created_at: datetime


class VerificationHistory(BaseModel):
    edge_id: uuid.UUID
    specs: list[VerificationSpecRead]
    runs: list[VerificationRunRead]


class PublicAnalysisSummary(BaseModel):
    public_slug: str
    title: str
    description: str
    category: str | None
    occurred_at: datetime | None
    weakest_confidence_grade: ConfidenceGrade
    confidence_product: Decimal | None
    published_at: datetime
    updated_at: datetime


class PublicAnalysisDetail(BaseModel):
    summary: PublicAnalysisSummary
    event: PublicEventRead
    graph: PublicChainGraph
    evidence_by_edge: dict[str, list[PublicEdgeEvidenceRead]]
    verification_by_edge: dict[str, VerificationHistory]


class PublicationReviewRead(ORMModel):
    id: uuid.UUID
    chain_version_id: uuid.UUID
    requested_reason: str
    gate_result: dict[str, Any]
    status: ReviewDecision
    reviewer_id: str | None
    decision_notes: str | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReviewDecisionRequest(BaseModel):
    decision: Literal[ReviewDecision.APPROVED, ReviewDecision.REJECTED]
    reviewer_id: str = Field(min_length=1, max_length=160)
    notes: str = Field(min_length=3, max_length=5000)


class GateReasonSchema(BaseModel):
    code: str
    message: str
    edge_id: uuid.UUID | None = None


class PublicationGateResponse(BaseModel):
    decision: PublicationDecision
    reasons: list[GateReasonSchema]
    excluded_ticker_exposure_ids: list[uuid.UUID]
    evaluated_edge_count: int


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    database: Literal["ok", "unavailable"] | None = None
