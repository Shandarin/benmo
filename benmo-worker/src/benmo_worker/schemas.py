from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
LongText = Annotated[str, StringConstraints(min_length=1, max_length=10_000_000)]
MetricCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:/-]{1,160}$")]


def utc_now() -> datetime:
    return datetime.now(UTC)


def canonical_json(value: BaseModel | dict[str, Any] | list[Any]) -> bytes:
    raw = value.model_dump(mode="json", exclude_none=False) if isinstance(value, BaseModel) else value
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_sha256(value: BaseModel | dict[str, Any] | list[Any] | bytes | str) -> str:
    if isinstance(value, bytes):
        raw = value
    elif isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raw = canonical_json(value)
    return hashlib.sha256(raw).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)


class Direction(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"


class ExpectedDirection(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"
    STABLE = "stable"


class RelationType(StrEnum):
    INPUT_COST = "input_cost"
    SELLING_PRICE = "selling_price"
    DEMAND = "demand"
    SUPPLY = "supply"
    FINANCING_COST = "financing_cost"
    CURRENCY_TRANSLATION = "currency_translation"
    REGULATORY_COST = "regulatory_cost"
    INVENTORY_PRICE_PRESSURE = "inventory_price_pressure"
    CAPACITY_DISRUPTION = "capacity_disruption"
    GUIDANCE_DEMAND = "guidance_demand"


class TimeScale(StrEnum):
    DAYS = "days"
    WEEKS = "weeks"
    NEXT_QUARTER = "next_quarter"
    ONE_TO_FOUR_QUARTERS = "one_to_four_quarters"
    LONG_TERM = "long_term"


class NodeType(StrEnum):
    EVENT = "event"
    COMMODITY = "commodity"
    MACRO = "macro"
    INDUSTRY = "industry"
    COMPANY = "company"
    COMPANY_METRIC = "company_metric"
    MARKET_PRICE = "market_price"
    REGULATION = "regulation"
    CAPACITY = "capacity"
    INVENTORY = "inventory"
    TICKER = "ticker"


class FactStatus(StrEnum):
    VERIFIED = "verified_fact"
    UNVERIFIED = "unverified"


class AtomicFact(StrictModel):
    subject: ShortText
    metric: ShortText
    value: Decimal | None = None
    unit: Annotated[str, StringConstraints(max_length=64)] | None = None
    change_pct: Decimal | None = None
    period: ShortText | None = None
    observed_at: datetime | None = None
    status: FactStatus
    source_hint: ShortText | None = None


class AnalysisRequest(StrictModel):
    analysis_id: str = Field(default_factory=lambda: f"ana_{uuid4().hex}")
    query: NonEmpty
    occurred_at: datetime | None = None
    locale: str = "zh-CN"


class NormalizedEvent(StrictModel):
    analysis_id: str
    claimed_event: ShortText
    observed_facts: list[AtomicFact] = Field(default_factory=list, max_length=50)
    unverified_claims: list[ShortText] = Field(default_factory=list, max_length=50)
    normalized_at: datetime = Field(default_factory=utc_now)


class CandidateNode(StrictModel):
    node_id: str = Field(default_factory=lambda: f"node_{uuid4().hex}")
    label: ShortText
    node_type: NodeType
    entity_ref: str | None = None


class CandidateEdge(StrictModel):
    edge_id: str = Field(default_factory=lambda: f"edge_{uuid4().hex}")
    from_node: ShortText
    to_node: ShortText
    from_node_type: NodeType
    to_node_type: NodeType
    relation_type: RelationType
    direction: Direction
    mechanism: NonEmpty
    conditions: list[ShortText] = Field(default_factory=list, max_length=20)
    invalidation_conditions: list[ShortText] = Field(default_factory=list, max_length=20)
    evidence_search_queries: list[ShortText] = Field(min_length=1, max_length=10)
    verification_metric: MetricCode | None = None
    source_adapter: str | None = None
    time_scale: TimeScale
    ticker: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9.-]{0,9}$")
    created_by_model_run_id: UUID | None = None


class CandidateGraph(StrictModel):
    event: NormalizedEvent
    nodes: list[CandidateNode] = Field(default_factory=list, max_length=100)
    edges: list[CandidateEdge] = Field(default_factory=list, max_length=50)
    taxonomy_version: str = "causal-taxonomy-v1"


class SourceTier(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class SourceType(StrEnum):
    SEC_10K = "SEC_10K"
    SEC_10Q = "SEC_10Q"
    SEC_8K = "SEC_8K"
    COMPANY_IR = "COMPANY_IR"
    OFFICIAL_DATA = "OFFICIAL_DATA"
    TRANSCRIPT = "TRANSCRIPT"
    INDUSTRY = "INDUSTRY"
    NEWS = "NEWS"
    WEB = "WEB"
    STUB = "STUB"


class SearchHit(StrictModel):
    url: AnyHttpUrl | str
    title: ShortText
    snippet: NonEmpty
    publisher: ShortText
    published_at: datetime | None = None
    source_type: SourceType = SourceType.WEB
    tier: SourceTier = SourceTier.D
    query: ShortText


class SearchResultBundle(StrictModel):
    query: ShortText
    hits: list[SearchHit] = Field(default_factory=list, max_length=50)
    provider: str
    searched_at: datetime = Field(default_factory=utc_now)


class DocumentSnapshot(StrictModel):
    source_id: str = Field(default_factory=lambda: f"src_{uuid4().hex}")
    source_url: AnyHttpUrl | str
    source_type: SourceType
    tier: SourceTier
    publisher: ShortText
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=utc_now)
    content_type: str = "text/plain; charset=utf-8"
    content: LongText
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    object_key: str | None = None

    @model_validator(mode="after")
    def hash_matches_content(self) -> DocumentSnapshot:
        if content_sha256(self.content) != self.content_hash:
            raise ValueError("content_hash does not match content")
        return self


class SupportLevel(StrEnum):
    DIRECT = "direct"
    PARTIAL = "partial"
    CONTRADICTORY = "contradictory"


class EvidenceSpan(StrictModel):
    evidence_id: str = Field(default_factory=lambda: f"ev_{uuid4().hex}")
    source_id: str
    source_url: AnyHttpUrl | str
    source_type: SourceType
    tier: SourceTier
    publisher: ShortText
    published_at: datetime | None = None
    retrieved_at: datetime
    quoted_span: NonEmpty
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    snapshot_object_key: str | None = None
    snapshot_content_type: str | None = None
    quote_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    supported_claim: NonEmpty
    support_level: SupportLevel
    limitations: list[ShortText] = Field(default_factory=list, max_length=20)
    independent_source_key: str

    @model_validator(mode="after")
    def validate_offsets_and_quote_hash(self) -> EvidenceSpan:
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        if content_sha256(self.quoted_span) != self.quote_hash:
            raise ValueError("quote_hash does not match quoted_span")
        return self


class EntailmentLabel(StrEnum):
    DIRECT = "directly_supports"
    PARTIAL = "partially_supports"
    NONE = "does_not_support"
    CONTRADICTS = "contradicts"


class EntailmentResult(StrictModel):
    label: EntailmentLabel
    rationale: ShortText
    provider: str


class EvaluatedEvidence(StrictModel):
    span: EvidenceSpan
    entailment: EntailmentResult


class EdgeResearchResult(StrictModel):
    edge: CandidateEdge
    supporting: list[EvaluatedEvidence] = Field(default_factory=list)
    adversarial: list[EvaluatedEvidence] = Field(default_factory=list)
    unavailable_urls: list[str] = Field(default_factory=list)


class BaselineRule(StrEnum):
    PROVIDED = "provided"
    PREVIOUS_OBSERVATION = "previous_observation"
    SAME_PERIOD_PRIOR_YEAR = "same_period_prior_year"
    EVENT_PREVIOUS_5D_MEAN = "event_previous_5d_mean"


class ComparatorOperation(StrEnum):
    CHANGE_PCT_GTE = "change_pct_gte"
    CHANGE_PCT_LTE = "change_pct_lte"
    ABS_CHANGE_PCT_GTE = "abs_change_pct_gte"
    VALUE_GTE = "value_gte"
    VALUE_LTE = "value_lte"


class ObservationWindow(StrictModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def ordered(self) -> ObservationWindow:
        if self.end <= self.start:
            raise ValueError("observation window end must be after start")
        return self


class VerificationSpec(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    spec_id: str = Field(default_factory=lambda: f"spec_{uuid4().hex}")
    edge_id: str
    metric_code: MetricCode
    source_adapter: str
    expected_direction: ExpectedDirection
    threshold: Decimal = Field(ge=0)
    baseline_rule: BaselineRule
    baseline_value: Decimal | None = None
    observation_window: ObservationWindow
    comparator: ComparatorOperation
    minimum_observations: int = Field(default=1, ge=1, le=1_000)
    spec_version: int = Field(default=1, ge=1)
    locked_at: datetime = Field(default_factory=utc_now)
    spec_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_baseline(self) -> VerificationSpec:
        if self.baseline_rule == BaselineRule.PROVIDED and self.baseline_value is None:
            raise ValueError("baseline_value is required when baseline_rule is provided")
        return self

    def with_hash(self) -> VerificationSpec:
        data = self.model_dump(mode="json", exclude={"spec_hash"})
        return self.model_copy(update={"spec_hash": content_sha256(data)})


class Observation(StrictModel):
    metric_code: MetricCode
    observed_value: Decimal
    baseline_value: Decimal | None = None
    observed_at: datetime
    source_adapter: str
    source_ref: str
    vintage_at: datetime | None = None
    sample_count: int = Field(default=1, ge=1)


class OutcomeStatus(StrEnum):
    PENDING = "pending"
    MONITORING = "monitoring"
    VERIFIED = "verified"
    PARTIAL = "partial"
    FALSIFIED = "falsified"
    INCONCLUSIVE = "inconclusive"
    EXPIRED = "expired"


class VerificationResult(StrictModel):
    run_id: str = Field(default_factory=lambda: f"vrun_{uuid4().hex}")
    spec_id: str
    spec_hash: str
    status: OutcomeStatus
    observed_value: Decimal | None = None
    baseline_value: Decimal | None = None
    change_pct: Decimal | None = None
    threshold: Decimal
    evaluated_at: datetime = Field(default_factory=utc_now)
    evaluated_by: Literal["deterministic_rule"] = "deterministic_rule"
    reason: NonEmpty
    observation_source_ref: str | None = None


class ContradictionLevel(StrEnum):
    NONE = "none"
    MINOR = "minor"
    MATERIAL = "material"


class EvidenceStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partially_supported"
    CONTESTED = "contested"
    UNSUPPORTED = "unsupported"
    SOURCE_EXPIRED = "source_expired"


class ConfidenceGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    INSUFFICIENT = "Insufficient"


class PublicationGateInput(StrictModel):
    edge_id: str
    evidence: list[EvaluatedEvidence]
    adversarial_evidence: list[EvaluatedEvidence] = Field(default_factory=list)
    indicator_executable: bool
    ticker: str | None = None
    ticker_exposure_evidence: list[str] = Field(default_factory=list)


class GateAction(StrEnum):
    PUBLISH = "publish"
    REVIEW = "human_review"
    REJECT = "reject"


class PublicationGateDecision(StrictModel):
    edge_id: str
    action: GateAction
    evidence_status: EvidenceStatus
    confidence_grade: ConfidenceGrade
    reasons: list[ShortText]
    direct_support_count: int = Field(ge=0)
    primary_source_count: int = Field(ge=0)
    independent_secondary_count: int = Field(ge=0)
    contradiction_level: ContradictionLevel
    ticker_removed: bool = False


class ChainVersion(StrictModel):
    chain_id: str
    version: int = Field(ge=1)
    analysis_id: str
    event: NormalizedEvent
    edges: list[EdgeResearchResult]
    verification_specs: list[VerificationSpec]
    gate_decisions: list[PublicationGateDecision]
    created_at: datetime = Field(default_factory=utc_now)
    workflow_version: str
    content_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    def immutable(self) -> ChainVersion:
        data = self.model_dump(mode="json", exclude={"content_hash"})
        return self.model_copy(update={"content_hash": content_sha256(data)})


class AnalysisOutcome(StrictModel):
    analysis_id: str
    action: GateAction
    chain_version: ChainVersion
    rejected_edge_ids: list[str] = Field(default_factory=list)
    review_edge_ids: list[str] = Field(default_factory=list)


class ModelRunRecord(StrictModel):
    run_id: UUID = Field(default_factory=uuid4)
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
    error_message: str | None = Field(default=None, max_length=4_000)


class TaskType(StrEnum):
    ANALYSIS_RESEARCH = "analysis.research"
    DOCUMENT_FETCH = "document.fetch"
    DOCUMENT_FILING = "document.filing"
    VERIFICATION_RUN = "verification.run"
    MANUAL_REVIEW = "manual.review"


class DocumentFetchPayload(StrictModel):
    url: NonEmpty
    claim: NonEmpty
    query: ShortText
    title: ShortText = "Fetched source"
    publisher: ShortText = "unknown"
    source_type: SourceType = SourceType.WEB
    tier: SourceTier = SourceTier.D
    adversarial: bool = False


class DocumentFilingPayload(StrictModel):
    cik_or_ticker: ShortText
    form: Literal["10-K", "10-Q", "8-K"]
    claim: NonEmpty | None = None


class VerificationTaskPayload(StrictModel):
    spec: VerificationSpec
    observation_time: datetime


class ManualReviewPayload(StrictModel):
    analysis_id: str
    edge_ids: list[str] = Field(min_length=1)
    reasons: list[ShortText] = Field(min_length=1)


class TaskMessage(StrictModel):
    task_id: UUID = Field(default_factory=uuid4)
    task_type: TaskType
    entity_id: str
    source_version: str
    workflow_version: str
    payload: (
        AnalysisRequest | DocumentFetchPayload | DocumentFilingPayload | VerificationTaskPayload | ManualReviewPayload
    )
    created_at: datetime = Field(default_factory=utc_now)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def idempotency_key(self) -> str:
        raw = ":".join((self.task_type.value, self.entity_id, self.source_version, self.workflow_version))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @field_validator("payload")
    @classmethod
    def payload_size(
        cls,
        value: (
            AnalysisRequest
            | DocumentFetchPayload
            | DocumentFilingPayload
            | VerificationTaskPayload
            | ManualReviewPayload
        ),
    ) -> AnalysisRequest | DocumentFetchPayload | DocumentFilingPayload | VerificationTaskPayload | ManualReviewPayload:
        if len(canonical_json(value)) > 240_000:
            raise ValueError("payload exceeds safe SQS message size")
        return value

    @model_validator(mode="after")
    def task_payload_matches(self) -> TaskMessage:
        expected: dict[TaskType, type[BaseModel]] = {
            TaskType.ANALYSIS_RESEARCH: AnalysisRequest,
            TaskType.DOCUMENT_FETCH: DocumentFetchPayload,
            TaskType.DOCUMENT_FILING: DocumentFilingPayload,
            TaskType.VERIFICATION_RUN: VerificationTaskPayload,
            TaskType.MANUAL_REVIEW: ManualReviewPayload,
        }
        if not isinstance(self.payload, expected[self.task_type]):
            raise ValueError(f"payload does not match task_type {self.task_type}")
        return self


class TaskClaim(StrictModel):
    claimed: bool
    previous_result: dict[str, Any] | None = None


class ProviderObservationRequest(StrictModel):
    metric_code: MetricCode
    observation_time: datetime
    baseline_rule: BaselineRule
