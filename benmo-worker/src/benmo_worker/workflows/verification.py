from __future__ import annotations

from benmo_worker.ports import IndicatorAdapter
from benmo_worker.schemas import VerificationResult, VerificationTaskPayload
from benmo_worker.verification import DeterministicVerifier


class VerificationWorkflow:
    def __init__(self, indicators: IndicatorAdapter, verifier: DeterministicVerifier) -> None:
        self.indicators = indicators
        self.verifier = verifier

    async def run(self, payload: VerificationTaskPayload) -> VerificationResult:
        observation = await self.indicators.fetch(payload.spec, payload.observation_time)
        return self.verifier.evaluate(payload.spec, observation, evaluated_at=payload.observation_time)
