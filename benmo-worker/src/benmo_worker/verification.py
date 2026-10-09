from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TypedDict

from benmo_worker.schemas import (
    ComparatorOperation,
    Observation,
    OutcomeStatus,
    VerificationResult,
    VerificationSpec,
    content_sha256,
    utc_now,
)


class _CommonResult(TypedDict):
    spec_id: str
    spec_hash: str
    threshold: Decimal
    evaluated_at: datetime
    observation_source_ref: str


class DeterministicVerifier:
    """Safe comparator engine. It intentionally accepts no executable expressions."""

    def evaluate(
        self,
        spec: VerificationSpec,
        observation: Observation,
        evaluated_at: datetime | None = None,
    ) -> VerificationResult:
        now = evaluated_at or utc_now()
        spec_hash = spec.spec_hash or content_sha256(spec.model_dump(mode="json", exclude={"spec_hash"}))
        common: _CommonResult = {
            "spec_id": spec.spec_id,
            "spec_hash": spec_hash,
            "threshold": spec.threshold,
            "evaluated_at": now,
            "observation_source_ref": observation.source_ref,
        }
        if observation.metric_code != spec.metric_code:
            return VerificationResult(
                **common,
                status=OutcomeStatus.INCONCLUSIVE,
                reason="observation metric does not match the locked verification spec",
            )
        if now < spec.observation_window.start:
            return VerificationResult(
                **common,
                status=OutcomeStatus.PENDING,
                reason="verification window has not started",
            )
        if observation.observed_at > spec.observation_window.end:
            return VerificationResult(
                **common,
                status=OutcomeStatus.EXPIRED,
                reason="observation falls after the locked verification window",
            )
        if observation.sample_count < spec.minimum_observations:
            return VerificationResult(
                **common,
                status=OutcomeStatus.INCONCLUSIVE,
                reason="not enough observations for the locked rule",
            )
        baseline = spec.baseline_value if spec.baseline_value is not None else observation.baseline_value
        change_pct: Decimal | None = None
        if spec.comparator in {
            ComparatorOperation.CHANGE_PCT_GTE,
            ComparatorOperation.CHANGE_PCT_LTE,
            ComparatorOperation.ABS_CHANGE_PCT_GTE,
        }:
            if baseline is None or baseline == 0:
                return VerificationResult(
                    **common,
                    status=OutcomeStatus.INCONCLUSIVE,
                    observed_value=observation.observed_value,
                    reason="baseline is missing or zero",
                )
            change_pct = ((observation.observed_value - baseline) / abs(baseline) * Decimal("100")).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        passed = self._compare(spec.comparator, observation.observed_value, change_pct, spec.threshold)
        if passed:
            status = OutcomeStatus.VERIFIED
            reason = "observation satisfies the preregistered comparator"
        elif change_pct is not None and self._same_direction(spec.comparator, change_pct):
            status = OutcomeStatus.PARTIAL
            reason = "direction matches but the preregistered threshold was not reached"
        elif change_pct is not None:
            status = OutcomeStatus.FALSIFIED
            reason = "observation moves against the preregistered direction"
        else:
            status = OutcomeStatus.FALSIFIED
            reason = "observation does not satisfy the preregistered value comparator"
        return VerificationResult(
            **common,
            status=status,
            observed_value=observation.observed_value,
            baseline_value=baseline,
            change_pct=change_pct,
            reason=reason,
        )

    def _compare(
        self,
        operation: ComparatorOperation,
        value: Decimal,
        change_pct: Decimal | None,
        threshold: Decimal,
    ) -> bool:
        if operation == ComparatorOperation.CHANGE_PCT_GTE:
            return change_pct is not None and change_pct >= threshold
        if operation == ComparatorOperation.CHANGE_PCT_LTE:
            return change_pct is not None and change_pct <= -threshold
        if operation == ComparatorOperation.ABS_CHANGE_PCT_GTE:
            return change_pct is not None and abs(change_pct) >= threshold
        if operation == ComparatorOperation.VALUE_GTE:
            return value >= threshold
        if operation == ComparatorOperation.VALUE_LTE:
            return value <= threshold
        raise AssertionError(f"unhandled comparator: {operation}")

    def _same_direction(self, operation: ComparatorOperation, change_pct: Decimal) -> bool:
        if operation == ComparatorOperation.CHANGE_PCT_GTE:
            return change_pct > 0
        if operation == ComparatorOperation.CHANGE_PCT_LTE:
            return change_pct < 0
        if operation == ComparatorOperation.ABS_CHANGE_PCT_GTE:
            return change_pct != 0
        return False
