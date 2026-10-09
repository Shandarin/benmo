from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class InternalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TaskClaimRequest(InternalModel):
    idempotency_key: str = Field(min_length=16, max_length=240)
    task_type: str = Field(min_length=1, max_length=80)
    entity_id: str = Field(min_length=1, max_length=160)
    workflow_version: str = Field(min_length=1, max_length=100)


class TaskClaimResponse(InternalModel):
    claimed: bool
    previous_result: dict[str, Any] | None = None


class TaskProgressRequest(InternalModel):
    stage: str = Field(min_length=1, max_length=100)
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class TaskCompleteRequest(InternalModel):
    result: dict[str, Any] = Field(default_factory=dict)


class TaskFailRequest(InternalModel):
    error: str = Field(min_length=1, max_length=4000)
    retryable: bool = True


class AnalysisProgressRequest(InternalModel):
    stage: str = Field(min_length=1, max_length=100)
    progress_percent: int = Field(ge=0, le=100)
    message: str = Field(min_length=1, max_length=2000)
    event_type: str = Field(default="analysis.progress", min_length=1, max_length=100)
    data: dict[str, Any] = Field(default_factory=dict)
    workflow_run_id: uuid.UUID | None = None


class AnalysisFailRequest(InternalModel):
    error_code: str = Field(min_length=1, max_length=80)
    error_message: str = Field(min_length=1, max_length=4000)
    stage: str = Field(default="failed", min_length=1, max_length=100)
    workflow_run_id: uuid.UUID | None = None


class AtomicFactIn(InternalModel):
    subject: str
    metric: str
    value: Decimal | None = None
    unit: str | None = None
    change_pct: Decimal | None = None
    period: str | None = None
    observed_at: datetime | None = None
    status: str
    source_hint: str | None = None


class NormalizedEventIn(InternalModel):
    analysis_id: str
    claimed_event: str
    observed_facts: list[AtomicFactIn] = Field(default_factory=list)
    unverified_claims: list[str] = Field(default_factory=list)
    normalized_at: datetime


class CandidateEdgeIn(InternalModel):
    edge_id: str
    from_node: str
    to_node: str
    from_node_type: str
    to_node_type: str
    relation_type: str
    direction: str
    mechanism: str
    conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    evidence_search_queries: list[str]
    verification_metric: str | None = None
    source_adapter: str | None = None
    time_scale: str
    ticker: str | None = None
    created_by_model_run_id: uuid.UUID | None = None


class EvidenceSpanIn(InternalModel):
    evidence_id: str
    source_id: str
    source_url: str
    source_type: str
    tier: Literal["A", "B", "C", "D"]
    publisher: str
    published_at: datetime | None = None
    retrieved_at: datetime
    quoted_span: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    snapshot_hash: str
    snapshot_object_key: str | None = None
    snapshot_content_type: str | None = None
    quote_hash: str
    supported_claim: str
    support_level: str
    limitations: list[str] = Field(default_factory=list)
    independent_source_key: str


class EntailmentIn(InternalModel):
    label: str
    rationale: str
    provider: str


class EvaluatedEvidenceIn(InternalModel):
    span: EvidenceSpanIn
    entailment: EntailmentIn


class EdgeResearchResultIn(InternalModel):
    edge: CandidateEdgeIn
    supporting: list[EvaluatedEvidenceIn] = Field(default_factory=list)
    adversarial: list[EvaluatedEvidenceIn] = Field(default_factory=list)
    unavailable_urls: list[str] = Field(default_factory=list)


class ObservationWindowIn(InternalModel):
    start: datetime
    end: datetime


class VerificationSpecIn(InternalModel):
    spec_id: str
    edge_id: str
    metric_code: str
    source_adapter: str
    expected_direction: str
    threshold: Decimal
    baseline_rule: str
    baseline_value: Decimal | None = None
    observation_window: ObservationWindowIn
    comparator: str
    minimum_observations: int
    spec_version: int
    locked_at: datetime
    spec_hash: str | None = None


class PublicationGateDecisionIn(InternalModel):
    edge_id: str
    action: Literal["publish", "human_review", "reject"]
    evidence_status: str
    confidence_grade: Literal["A", "B", "C", "Insufficient"]
    reasons: list[str]
    direct_support_count: int
    primary_source_count: int
    independent_secondary_count: int
    contradiction_level: Literal["none", "minor", "material"]
    ticker_removed: bool = False


class WorkerChainVersionIn(InternalModel):
    chain_id: str
    version: int = Field(ge=1)
    analysis_id: str
    event: NormalizedEventIn
    edges: list[EdgeResearchResultIn]
    verification_specs: list[VerificationSpecIn]
    gate_decisions: list[PublicationGateDecisionIn]
    created_at: datetime
    workflow_version: str
    content_hash: str


class AnalysisOutcomeIn(InternalModel):
    analysis_id: str
    action: Literal["publish", "human_review", "reject"]
    chain_version: WorkerChainVersionIn
    rejected_edge_ids: list[str] = Field(default_factory=list)
    review_edge_ids: list[str] = Field(default_factory=list)


class AnalysisCompletionResponse(InternalModel):
    analysis_id: uuid.UUID
    chain_id: uuid.UUID
    chain_version_id: uuid.UUID
    status: str
    idempotent_replay: bool = False


class ModelRunIn(InternalModel):
    run_id: uuid.UUID
    provider: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=100)
    prompt_template_version: str = Field(min_length=1, max_length=100)
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    raw_response_storage_key: str | None = None
    structured_output: dict[str, Any] = Field(default_factory=dict)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    search_count: int = Field(default=0, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    started_at: datetime
    completed_at: datetime | None = None
    status: Literal["success", "failed"]
    error_message: str | None = Field(default=None, max_length=4000)
