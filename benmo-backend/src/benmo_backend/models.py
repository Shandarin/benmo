from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from benmo_backend.db import Base
from benmo_backend.enums import (
    AnalysisStatus,
    ChainStatus,
    ConfidenceGrade,
    EntailmentStatus,
    EvidenceStatus,
    OutcomeStatus,
    ReviewDecision,
    SourceTier,
    WorkflowStatus,
)

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Event(Base, TimestampMixin):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="candidate", index=True)
    source_input: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)

    facts: Mapped[list[EventFact]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    analyses: Mapped[list[Analysis]] = relationship(back_populates="event")
    chains: Mapped[list[Chain]] = relationship(back_populates="event")


class Analysis(Base, TimestampMixin):
    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), index=True
    )
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    input_context: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    status: Mapped[str] = mapped_column(
        String(32), default=AnalysisStatus.QUEUED.value, nullable=False, index=True
    )
    current_stage: Mapped[str] = mapped_column(String(64), default="queued", nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    public_slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    event: Mapped[Event | None] = relationship(back_populates="analyses")
    progress_events: Mapped[list[AnalysisProgressEvent]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="AnalysisProgressEvent.sequence",
    )
    workflow_runs: Mapped[list[WorkflowRun]] = relationship(back_populates="analysis")


class AnalysisProgressEvent(Base):
    __tablename__ = "analysis_progress_events"
    __table_args__ = (UniqueConstraint("analysis_id", "sequence"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    analysis: Mapped[Analysis] = relationship(back_populates="progress_events")


class EventFact(Base, TimestampMixin):
    __tablename__ = "event_facts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    metric_code: Mapped[str | None] = mapped_column(String(160), index=True)
    observed_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    unit: Mapped[str | None] = mapped_column(String(40))
    period: Mapped[str | None] = mapped_column(String(100))
    fact_status: Mapped[str] = mapped_column(String(32), default="unverified_claim", index=True)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_documents.id", ondelete="SET NULL")
    )
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)

    event: Mapped[Event] = relationship(back_populates="facts")
    source_document: Mapped[EvidenceDocument | None] = relationship()


class Chain(Base, TimestampMixin):
    __tablename__ = "chains"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=ChainStatus.DRAFT.value, nullable=False, index=True
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "chain_versions.id",
            name="fk_chains_current_version_id_chain_versions",
            use_alter=True,
            ondelete="SET NULL",
        )
    )
    weakest_confidence_grade: Mapped[str] = mapped_column(
        String(20), default=ConfidenceGrade.INSUFFICIENT.value
    )
    confidence_product: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    event: Mapped[Event] = relationship(back_populates="chains")
    versions: Mapped[list[ChainVersion]] = relationship(
        back_populates="chain",
        cascade="all, delete-orphan",
        foreign_keys="ChainVersion.chain_id",
        order_by="ChainVersion.version",
    )
    current_version: Mapped[ChainVersion | None] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )


class ChainVersion(Base):
    __tablename__ = "chain_versions"
    __table_args__ = (UniqueConstraint("chain_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    chain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chains.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_by_model_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    chain: Mapped[Chain] = relationship(back_populates="versions", foreign_keys=[chain_id])
    nodes: Mapped[list[Node]] = relationship(
        back_populates="chain_version", cascade="all, delete-orphan"
    )
    edges: Mapped[list[CausalEdge]] = relationship(
        back_populates="chain_version", cascade="all, delete-orphan"
    )


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (UniqueConstraint("chain_version_id", "key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    chain_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chain_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    metric_code: Mapped[str | None] = mapped_column(String(160))
    entity_ref: Mapped[str | None] = mapped_column(String(160))
    attributes: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    chain_version: Mapped[ChainVersion] = relationship(back_populates="nodes")


class CausalEdge(Base, TimestampMixin):
    __tablename__ = "causal_edges"
    __table_args__ = (
        Index("ix_causal_edges_version_nodes", "chain_version_id", "from_node_id", "to_node_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    chain_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chain_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="RESTRICT"), nullable=False
    )
    to_node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="RESTRICT"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    mechanism: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_status: Mapped[str] = mapped_column(
        String(32), default=EvidenceStatus.UNSUPPORTED.value, nullable=False, index=True
    )
    outcome_status: Mapped[str] = mapped_column(
        String(32), default=OutcomeStatus.PENDING.value, nullable=False, index=True
    )
    confidence_grade: Mapped[str] = mapped_column(
        String(20), default=ConfidenceGrade.INSUFFICIENT.value, nullable=False
    )
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    confidence_breakdown: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_model_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL")
    )

    chain_version: Mapped[ChainVersion] = relationship(back_populates="edges")
    from_node: Mapped[Node] = relationship(foreign_keys=[from_node_id])
    to_node: Mapped[Node] = relationship(foreign_keys=[to_node_id])
    conditions: Mapped[list[Condition]] = relationship(
        back_populates="edge", cascade="all, delete-orphan"
    )
    evidence_links: Mapped[list[EdgeEvidence]] = relationship(
        back_populates="edge", cascade="all, delete-orphan"
    )
    verification_specs: Mapped[list[VerificationSpec]] = relationship(
        back_populates="edge",
        cascade="save-update, merge",
        order_by="VerificationSpec.spec_version",
    )
    ticker_exposures: Mapped[list[TickerExposure]] = relationship(back_populates="edge")


class Condition(Base):
    __tablename__ = "conditions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    edge_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("causal_edges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    edge: Mapped[CausalEdge] = relationship(back_populates="conditions")


class EvidenceDocument(Base, TimestampMixin):
    __tablename__ = "evidence_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_tier: Mapped[str] = mapped_column(String(1), default=SourceTier.D.value, index=True)
    publisher: Mapped[str | None] = mapped_column(String(240), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_key: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(120))
    snapshot_text: Mapped[str | None] = mapped_column(Text)
    is_accessible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)

    spans: Mapped[list[EvidenceSpan]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class EvidenceSpan(Base):
    __tablename__ = "evidence_spans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quoted_span: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    supported_claim: Mapped[str] = mapped_column(Text, nullable=False)
    support_level: Mapped[str] = mapped_column(String(32), nullable=False)
    limitations: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    quote_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[EvidenceDocument] = relationship(back_populates="spans")
    edge_links: Mapped[list[EdgeEvidence]] = relationship(
        back_populates="span", cascade="all, delete-orphan"
    )


class EdgeEvidence(Base):
    __tablename__ = "edge_evidence"
    __table_args__ = (UniqueConstraint("edge_id", "evidence_span_id", "role"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    edge_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("causal_edges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_span_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_spans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), default="support", nullable=False)
    entailment_status: Mapped[str] = mapped_column(
        String(32), default=EntailmentStatus.DOES_NOT_SUPPORT.value, nullable=False
    )
    is_direct: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    independent_source_key: Mapped[str | None] = mapped_column(String(240), index=True)
    contradiction_level: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    edge: Mapped[CausalEdge] = relationship(back_populates="evidence_links")
    span: Mapped[EvidenceSpan] = relationship(back_populates="edge_links")


class ImmutableVerificationSpecError(ValueError):
    """Raised when code attempts to change an already preregistered rule."""


class VerificationSpec(Base):
    __tablename__ = "verification_specs"
    __table_args__ = (UniqueConstraint("edge_id", "spec_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    edge_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("causal_edges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_code: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_adapter: Mapped[str] = mapped_column(String(80), nullable=False)
    expected_direction: Mapped[str] = mapped_column(String(20), nullable=False)
    threshold: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    baseline_rule: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    observation_window: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    comparator_expression: Mapped[str] = mapped_column(Text, nullable=False)
    spec_version: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("verification_specs.id", ondelete="RESTRICT")
    )
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    edge: Mapped[CausalEdge] = relationship(back_populates="verification_specs")
    runs: Mapped[list[VerificationRun]] = relationship(back_populates="spec")
    observations: Mapped[list[IndicatorObservation]] = relationship(back_populates="spec")
    supersedes: Mapped[VerificationSpec | None] = relationship(remote_side=[id])


@event.listens_for(VerificationSpec, "before_update", propagate=True)
def prevent_locked_spec_update(_: object, __: object, target: VerificationSpec) -> None:
    if target.locked_at is not None:
        raise ImmutableVerificationSpecError(
            "Locked verification specs are immutable; create a new spec_version instead."
        )


@event.listens_for(VerificationSpec, "before_delete", propagate=True)
def prevent_locked_spec_delete(_: object, __: object, target: VerificationSpec) -> None:
    if target.locked_at is not None:
        raise ImmutableVerificationSpecError("Locked verification specs cannot be deleted.")


class VerificationRun(Base):
    __tablename__ = "verification_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    verification_spec_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("verification_specs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome_status: Mapped[str] = mapped_column(
        String(32), default=OutcomeStatus.PENDING.value, nullable=False, index=True
    )
    observed_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    baseline_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    threshold_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    evaluated_by: Mapped[str | None] = mapped_column(String(80))
    result: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    spec: Mapped[VerificationSpec] = relationship(back_populates="runs")


class IndicatorObservation(Base):
    __tablename__ = "indicator_observations"
    __table_args__ = (
        UniqueConstraint("metric_code", "source_adapter", "observed_at", "vintage_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    verification_spec_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("verification_specs.id", ondelete="SET NULL"), index=True
    )
    metric_code: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_adapter: Mapped[str] = mapped_column(String(80), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    vintage_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    unit: Mapped[str | None] = mapped_column(String(40))
    raw_payload_hash: Mapped[str | None] = mapped_column(String(64))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    spec: Mapped[VerificationSpec | None] = relationship(back_populates="observations")


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    legal_name: Mapped[str] = mapped_column(String(300), nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(24), index=True)
    exchange: Mapped[str | None] = mapped_column(String(40))
    cik: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    sector: Mapped[str | None] = mapped_column(String(160), index=True)
    industry: Mapped[str | None] = mapped_column(String(160), index=True)
    entity_metadata: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)

    exposures: Mapped[list[TickerExposure]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class TickerExposure(Base, TimestampMixin):
    __tablename__ = "ticker_exposures"
    __table_args__ = (UniqueConstraint("edge_id", "company_id", "exposure_type"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    edge_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("causal_edges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exposure_type: Mapped[str] = mapped_column(String(64), nullable=False)
    exposure_direction: Mapped[str] = mapped_column(String(20), nullable=False)
    materiality: Mapped[str] = mapped_column(String(20), nullable=False)
    time_scale: Mapped[str] = mapped_column(String(40), nullable=False)
    exposure_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON_TYPE, default=list)
    offsetting_factors: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    edge: Mapped[CausalEdge] = relationship(back_populates="ticker_exposures")
    company: Mapped[Company] = relationship(back_populates="exposures")


class ModelRun(Base):
    __tablename__ = "model_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    provider: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    prompt_template_version: Mapped[str] = mapped_column(String(100), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str | None] = mapped_column(String(64))
    raw_response_storage_key: Mapped[str | None] = mapped_column(Text)
    structured_output: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    search_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text)


class WorkflowRun(Base, TimestampMixin):
    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="SET NULL"), index=True
    )
    workflow_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    workflow_version: Mapped[str] = mapped_column(String(80), nullable=False)
    external_execution_id: Mapped[str | None] = mapped_column(String(240), index=True)
    queue_message_id: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(
        String(32), default=WorkflowStatus.QUEUED.value, nullable=False, index=True
    )
    current_step: Mapped[str | None] = mapped_column(String(100))
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    analysis: Mapped[Analysis | None] = relationship(back_populates="workflow_runs")


class PublicationReview(Base, TimestampMixin):
    __tablename__ = "publication_reviews"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    chain_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chain_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_reason: Mapped[str] = mapped_column(Text, nullable=False)
    gate_result: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    status: Mapped[str] = mapped_column(
        String(32), default=ReviewDecision.PENDING.value, nullable=False, index=True
    )
    reviewer_id: Mapped[str | None] = mapped_column(String(160))
    decision_notes: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(160), index=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    request_id: Mapped[str | None] = mapped_column(String(80), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    idempotency_key: Mapped[str] = mapped_column(
        String(240), unique=True, nullable=False, index=True
    )
    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source_version: Mapped[str] = mapped_column(String(100), nullable=False)
    workflow_version: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="accepted", nullable=False)
    response_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
