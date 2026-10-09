from __future__ import annotations

from benmo_worker.schemas import (
    ConfidenceGrade,
    ContradictionLevel,
    EntailmentLabel,
    EvidenceStatus,
    GateAction,
    PublicationGateDecision,
    PublicationGateInput,
    SourceTier,
)


class PublicationGate:
    """Deterministic product policy; scores are grades, never probabilities."""

    def evaluate(self, value: PublicationGateInput) -> PublicationGateDecision:
        direct = [item for item in value.evidence if item.entailment.label == EntailmentLabel.DIRECT]
        partial = [item for item in value.evidence if item.entailment.label == EntailmentLabel.PARTIAL]
        primary_keys = {item.span.independent_source_key for item in direct if item.span.tier == SourceTier.A}
        secondary_keys = {
            item.span.independent_source_key for item in direct if item.span.tier in {SourceTier.B, SourceTier.C}
        }
        contradictions = [
            item
            for item in (*value.evidence, *value.adversarial_evidence)
            if item.entailment.label == EntailmentLabel.CONTRADICTS
        ]
        if any(item.span.tier in {SourceTier.A, SourceTier.B} for item in contradictions):
            contradiction = ContradictionLevel.MATERIAL
        elif contradictions:
            contradiction = ContradictionLevel.MINOR
        else:
            contradiction = ContradictionLevel.NONE

        reasons: list[str] = []
        action = GateAction.PUBLISH
        if len(direct) < 1:
            reasons.append("at least one directly supporting span is required")
            action = GateAction.REJECT
        if not primary_keys and len(secondary_keys) < 2:
            reasons.append("requires one primary source or two independent professional/news sources")
            action = GateAction.REJECT
        if not value.indicator_executable:
            reasons.append("edge has no executable preregistered indicator")
            action = GateAction.REJECT
        if contradiction == ContradictionLevel.MATERIAL and action != GateAction.REJECT:
            reasons.append("material counterevidence requires a human decision")
            action = GateAction.REVIEW
        ticker_removed = bool(value.ticker and not value.ticker_exposure_evidence)
        if ticker_removed:
            reasons.append("ticker endpoint removed because exposure evidence is absent")
        if not reasons:
            reasons.append("all deterministic publication requirements passed")

        if contradiction != ContradictionLevel.NONE:
            evidence_status = EvidenceStatus.CONTESTED
        elif direct:
            evidence_status = EvidenceStatus.SUPPORTED
        elif partial:
            evidence_status = EvidenceStatus.PARTIAL
        else:
            evidence_status = EvidenceStatus.UNSUPPORTED

        score = 0
        score += 35 if primary_keys else min(25, len(secondary_keys) * 15)
        score += min(20, len({item.span.independent_source_key for item in direct}) * 10)
        score += 20 if direct else (10 if partial else 0)
        score += 20 if value.indicator_executable else 0
        score += 5 if value.ticker_exposure_evidence else 0
        score -= 25 if contradiction == ContradictionLevel.MATERIAL else (10 if contradictions else 0)
        if action == GateAction.REJECT:
            grade = ConfidenceGrade.INSUFFICIENT
        elif score >= 85:
            grade = ConfidenceGrade.A
        elif score >= 65:
            grade = ConfidenceGrade.B
        else:
            grade = ConfidenceGrade.C
        return PublicationGateDecision(
            edge_id=value.edge_id,
            action=action,
            evidence_status=evidence_status,
            confidence_grade=grade,
            reasons=reasons,
            direct_support_count=len(direct),
            primary_source_count=len(primary_keys),
            independent_secondary_count=len(secondary_keys),
            contradiction_level=contradiction,
            ticker_removed=ticker_removed,
        )
