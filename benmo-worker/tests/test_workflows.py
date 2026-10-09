from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from benmo_worker.app import build_application
from benmo_worker.config import Settings
from benmo_worker.errors import IntegrityError
from benmo_worker.evidence import verify_quote_exists
from benmo_worker.providers.openai import OpenAIProvider
from benmo_worker.schemas import (
    AnalysisRequest,
    BaselineRule,
    ComparatorOperation,
    DocumentSnapshot,
    EntailmentLabel,
    EvidenceSpan,
    ExpectedDirection,
    GateAction,
    ModelRunRecord,
    Observation,
    ObservationWindow,
    OutcomeStatus,
    SourceTier,
    SourceType,
    SupportLevel,
    TaskMessage,
    TaskType,
    VerificationSpec,
    content_sha256,
)
from benmo_worker.storage import LocalObjectStore
from benmo_worker.verification import DeterministicVerifier


async def test_stub_analysis_is_auditable_and_publishable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(
        env="test",
        provider_mode="stub",
        local_object_path=tmp_path / "objects",
        local_state_path=tmp_path / "worker.sqlite3",
    )
    app = build_application(settings)

    outcome = await app.analysis.run(
        AnalysisRequest(
            analysis_id="ana_worker_e2e",
            query="WTI crude oil rose 12% in five trading days.",
        )
    )

    assert outcome.action == GateAction.PUBLISH
    assert outcome.chain_version.content_hash is not None
    assert len(outcome.chain_version.edges) == 2
    assert len(outcome.chain_version.verification_specs) == 2
    assert all(spec.spec_hash for spec in outcome.chain_version.verification_specs)
    assert all(decision.action == GateAction.PUBLISH for decision in outcome.chain_version.gate_decisions)
    assert all(
        evidence.entailment.label == EntailmentLabel.DIRECT
        for edge in outcome.chain_version.edges
        for evidence in edge.supporting
        if evidence.span.tier == SourceTier.A
    )

    clean_snapshots = list((tmp_path / "objects" / "sources").rglob("clean.txt"))
    metadata_snapshots = list((tmp_path / "objects" / "sources").rglob("metadata.json"))
    assert clean_snapshots
    assert len(clean_snapshots) == len(metadata_snapshots)


def test_quote_integrity_rejects_tampering() -> None:
    content = "Fuel prices are a material component of airline operating expense."
    snapshot = DocumentSnapshot(
        source_id="src_quote",
        source_url="https://example.com/filing",
        source_type=SourceType.SEC_10K,
        tier=SourceTier.A,
        publisher="Example Airline",
        content=content,
        content_hash=content_sha256(content),
    )
    span = EvidenceSpan(
        evidence_id="ev_quote",
        source_id=snapshot.source_id,
        source_url=snapshot.source_url,
        source_type=snapshot.source_type,
        tier=snapshot.tier,
        publisher=snapshot.publisher,
        retrieved_at=snapshot.retrieved_at,
        quoted_span=content,
        start_offset=0,
        end_offset=len(content),
        snapshot_hash=snapshot.content_hash,
        quote_hash=content_sha256(content),
        supported_claim="Fuel prices affect airline operating costs.",
        support_level=SupportLevel.DIRECT,
        independent_source_key="example.com",
    )
    verify_quote_exists(snapshot, span)

    tampered = span.model_copy(update={"quoted_span": content.replace("material", "minor")})
    with pytest.raises(IntegrityError, match="does not exist"):
        verify_quote_exists(snapshot, tampered)


def test_deterministic_verifier_uses_locked_rule() -> None:
    now = datetime.now(UTC)
    spec = VerificationSpec(
        spec_id="spec_fuel_cost",
        edge_id="edge_fuel_cost",
        metric_code="airline.fuel_cost_per_asm",
        source_adapter="sec_xbrl",
        expected_direction=ExpectedDirection.INCREASE,
        threshold=Decimal("3"),
        baseline_rule=BaselineRule.PREVIOUS_OBSERVATION,
        observation_window=ObservationWindow(
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
        ),
        comparator=ComparatorOperation.CHANGE_PCT_GTE,
        locked_at=now - timedelta(days=2),
    ).with_hash()
    verifier = DeterministicVerifier()

    verified = verifier.evaluate(
        spec,
        Observation(
            metric_code=spec.metric_code,
            observed_value=Decimal("104"),
            baseline_value=Decimal("100"),
            observed_at=now,
            source_adapter=spec.source_adapter,
            source_ref="stub://verified",
        ),
        evaluated_at=now,
    )
    falsified = verifier.evaluate(
        spec,
        Observation(
            metric_code=spec.metric_code,
            observed_value=Decimal("98"),
            baseline_value=Decimal("100"),
            observed_at=now,
            source_adapter=spec.source_adapter,
            source_ref="stub://falsified",
        ),
        evaluated_at=now,
    )

    assert verified.status == OutcomeStatus.VERIFIED
    assert verified.change_pct == Decimal("4.0000")
    assert falsified.status == OutcomeStatus.FALSIFIED
    assert verified.spec_hash == spec.spec_hash


def test_task_contract_has_stable_four_part_idempotency_key() -> None:
    payload = AnalysisRequest(analysis_id="ana_contract", query="Copper rose 5%.")
    first = TaskMessage(
        task_type=TaskType.ANALYSIS_RESEARCH,
        entity_id=payload.analysis_id,
        source_version="request-v1",
        workflow_version="analysis-v1",
        payload=payload,
    )
    replay = TaskMessage(
        task_type=TaskType.ANALYSIS_RESEARCH,
        entity_id=payload.analysis_id,
        source_version="request-v1",
        workflow_version="analysis-v1",
        payload=payload,
    )

    assert first.task_id != replay.task_id
    assert first.idempotency_key == replay.idempotency_key
    with pytest.raises(ValidationError):
        TaskMessage.model_validate({**first.model_dump(), "unexpected": True})


async def test_openai_search_uses_sdk_filter_shape_and_records_audit(tmp_path) -> None:  # type: ignore[no-untyped-def]
    class FakeUsage:
        input_tokens = 12
        output_tokens = 8

    class FakeResponse:
        usage = FakeUsage()
        output_text = "research summary"

        def model_dump(self, mode: str) -> dict[str, object]:
            assert mode == "json"
            return {
                "output": [
                    {
                        "sources": [
                            {"url": "https://eia.gov/jet-fuel", "title": "EIA"},
                            {"url": "https://blocked.example/post", "title": "Blocked"},
                        ]
                    }
                ]
            }

    class FakeResponses:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] = {}

        async def create(self, **kwargs: object) -> FakeResponse:
            self.kwargs = kwargs
            return FakeResponse()

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    class AuditRepository:
        def __init__(self) -> None:
            self.records: list[ModelRunRecord] = []

        async def persist_model_run(self, record: ModelRunRecord) -> None:
            self.records.append(record)

    client = FakeClient()
    repository = AuditRepository()
    provider = OpenAIProvider(
        "test-key",
        "test-model",
        client=client,
        audit_repository=repository,  # type: ignore[arg-type]
        object_store=LocalObjectStore(tmp_path / "objects"),
    )

    result = await provider.search(
        "jet fuel price evidence",
        allowed_domains=["eia.gov"],
        blocked_domains=["blocked.example"],
    )

    tools = client.responses.kwargs["tools"]
    assert tools == [{"type": "web_search", "filters": {"allowed_domains": ["eia.gov"]}}]
    assert [str(hit.url) for hit in result.hits] == ["https://eia.gov/jet-fuel"]
    assert len(repository.records) == 1
    record = repository.records[0]
    assert record.purpose == "web_research"
    assert record.search_count == 1
    assert record.input_tokens == 12
    assert record.raw_response_storage_key is not None
    assert (tmp_path / "objects" / record.raw_response_storage_key).is_file()
