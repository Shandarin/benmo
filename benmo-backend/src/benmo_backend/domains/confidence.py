from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from benmo_backend.enums import ChainStatus, ConfidenceGrade, OutcomeStatus


@dataclass(frozen=True, slots=True)
class ConfidenceInputs:
    evidence_quality: float
    source_independence: float
    mechanism_match: float
    indicator_executability: float
    historical_consistency: float
    company_exposure_clarity: float
    contradiction_penalty: float = 0
    stale_data_penalty: float = 0
    causal_distance_penalty: float = 0


@dataclass(frozen=True, slots=True)
class EdgeConfidence:
    score: Decimal
    grade: ConfidenceGrade
    breakdown: dict[str, float]


@dataclass(frozen=True, slots=True)
class EdgeAggregateInput:
    score: float | Decimal | None
    grade: ConfidenceGrade
    outcome_status: OutcomeStatus
    is_critical: bool


@dataclass(frozen=True, slots=True)
class ChainAggregate:
    status: ChainStatus
    weakest_grade: ConfidenceGrade
    confidence_product: Decimal
    outcome_counts: dict[str, int]


_GRADE_ORDER = {
    ConfidenceGrade.INSUFFICIENT: 0,
    ConfidenceGrade.C: 1,
    ConfidenceGrade.B: 2,
    ConfidenceGrade.A: 3,
}


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def grade_for_score(score: float | Decimal) -> ConfidenceGrade:
    value = float(score)
    if value >= 85:
        return ConfidenceGrade.A
    if value >= 70:
        return ConfidenceGrade.B
    if value >= 55:
        return ConfidenceGrade.C
    return ConfidenceGrade.INSUFFICIENT


def compute_edge_confidence(inputs: ConfidenceInputs) -> EdgeConfidence:
    dimensions = {
        "evidence_quality": _bounded(inputs.evidence_quality),
        "source_independence": _bounded(inputs.source_independence),
        "mechanism_match": _bounded(inputs.mechanism_match),
        "indicator_executability": _bounded(inputs.indicator_executability),
        "historical_consistency": _bounded(inputs.historical_consistency),
        "company_exposure_clarity": _bounded(inputs.company_exposure_clarity),
    }
    weighted = (
        0.28 * dimensions["evidence_quality"]
        + 0.18 * dimensions["source_independence"]
        + 0.18 * dimensions["mechanism_match"]
        + 0.14 * dimensions["indicator_executability"]
        + 0.12 * dimensions["historical_consistency"]
        + 0.10 * dimensions["company_exposure_clarity"]
    )
    penalties = {
        "contradiction_penalty": max(0.0, inputs.contradiction_penalty),
        "stale_data_penalty": max(0.0, inputs.stale_data_penalty),
        "causal_distance_penalty": max(0.0, inputs.causal_distance_penalty),
    }
    score_float = _bounded(weighted - sum(penalties.values()))
    score = Decimal(str(score_float)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return EdgeConfidence(
        score=score,
        grade=grade_for_score(score),
        breakdown={**dimensions, **penalties, "weighted_before_penalties": round(weighted, 4)},
    )


def aggregate_chain(edges: Iterable[EdgeAggregateInput]) -> ChainAggregate:
    items = list(edges)
    if not items:
        return ChainAggregate(
            status=ChainStatus.INCONCLUSIVE,
            weakest_grade=ConfidenceGrade.INSUFFICIENT,
            confidence_product=Decimal("0.00000"),
            outcome_counts={},
        )

    weakest = min((item.grade for item in items), key=_GRADE_ORDER.__getitem__)
    product = math.prod(max(0.0, min(100.0, float(item.score or 0))) / 100 for item in items)
    confidence_product = Decimal(str(product)).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
    counts = Counter(item.outcome_status.value for item in items)

    critical_falsified = any(
        item.is_critical and item.outcome_status == OutcomeStatus.FALSIFIED for item in items
    )
    all_falsified = all(item.outcome_status == OutcomeStatus.FALSIFIED for item in items)
    positive = sum(
        item.outcome_status in {OutcomeStatus.VERIFIED, OutcomeStatus.PARTIAL} for item in items
    )
    all_verified = all(item.outcome_status == OutcomeStatus.VERIFIED for item in items)
    any_falsified = any(item.outcome_status == OutcomeStatus.FALSIFIED for item in items)

    if critical_falsified or all_falsified:
        status = ChainStatus.BROKEN
    elif all_verified:
        status = ChainStatus.FULLY_SUPPORTED
    elif positive / len(items) >= 0.7 and not any_falsified:
        status = ChainStatus.MOSTLY_SUPPORTED
    elif positive > 0:
        status = ChainStatus.PARTIALLY_SUPPORTED
    else:
        status = ChainStatus.INCONCLUSIVE

    return ChainAggregate(
        status=status,
        weakest_grade=weakest,
        confidence_product=confidence_product,
        outcome_counts=dict(counts),
    )
