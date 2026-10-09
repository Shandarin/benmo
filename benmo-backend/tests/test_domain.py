from __future__ import annotations

import uuid
from decimal import Decimal

from benmo_backend.domains.confidence import (
    ConfidenceInputs,
    EdgeAggregateInput,
    aggregate_chain,
    compute_edge_confidence,
)
from benmo_backend.domains.publication import (
    EdgeForGate,
    EvidenceForGate,
    TickerExposureForGate,
    evaluate_publication_gate,
)
from benmo_backend.enums import (
    ChainStatus,
    ConfidenceGrade,
    OutcomeStatus,
    PublicationDecision,
    SourceTier,
)


def test_confidence_is_deterministic_and_penalized() -> None:
    result = compute_edge_confidence(
        ConfidenceInputs(
            evidence_quality=90,
            source_independence=80,
            mechanism_match=85,
            indicator_executability=100,
            historical_consistency=70,
            company_exposure_clarity=60,
            contradiction_penalty=5,
            causal_distance_penalty=3,
        )
    )
    assert result.score == Decimal("75.30")
    assert result.grade == ConfidenceGrade.B
    assert result.breakdown["contradiction_penalty"] == 5


def test_chain_breaks_when_a_critical_edge_is_falsified() -> None:
    result = aggregate_chain(
        [
            EdgeAggregateInput(90, ConfidenceGrade.A, OutcomeStatus.VERIFIED, True),
            EdgeAggregateInput(80, ConfidenceGrade.B, OutcomeStatus.FALSIFIED, True),
            EdgeAggregateInput(60, ConfidenceGrade.C, OutcomeStatus.VERIFIED, False),
        ]
    )
    assert result.status == ChainStatus.BROKEN
    assert result.weakest_grade == ConfidenceGrade.C
    assert result.outcome_counts == {"verified": 2, "falsified": 1}


def test_publication_gate_publishes_and_removes_unsupported_ticker() -> None:
    edge_id = uuid.uuid4()
    exposure_id = uuid.uuid4()
    result = evaluate_publication_gate(
        [
            EdgeForGate(
                edge_id=edge_id,
                evidence=(EvidenceForGate(True, True, SourceTier.A, "sec:issuer"),),
                has_executable_spec=True,
            )
        ],
        [TickerExposureForGate(exposure_id, False)],
    )
    assert result.decision == PublicationDecision.PUBLISH
    assert result.excluded_ticker_exposure_ids == (exposure_id,)


def test_publication_gate_rejects_missing_support_before_review() -> None:
    edge_id = uuid.uuid4()
    result = evaluate_publication_gate(
        [
            EdgeForGate(
                edge_id=edge_id,
                evidence=(EvidenceForGate(False, True, SourceTier.C, "news:a", "material"),),
                has_executable_spec=False,
            )
        ]
    )
    assert result.decision == PublicationDecision.REJECT
    assert {item.code for item in result.reasons} == {
        "direct_support_missing",
        "source_independence_insufficient",
        "verification_spec_missing",
        "material_contradiction",
    }
