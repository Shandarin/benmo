from __future__ import annotations

from benmo_worker.evidence import EvidenceProcessor
from benmo_worker.ports import SECProvider
from benmo_worker.schemas import (
    DocumentFetchPayload,
    DocumentFilingPayload,
    EvaluatedEvidence,
    SearchHit,
    SupportLevel,
)


class DocumentWorkflow:
    def __init__(self, evidence: EvidenceProcessor, sec: SECProvider) -> None:
        self.evidence = evidence
        self.sec = sec

    async def fetch_and_verify(self, payload: DocumentFetchPayload) -> EvaluatedEvidence:
        hit = SearchHit(
            url=payload.url,
            title=payload.title,
            snippet=payload.claim,
            publisher=payload.publisher,
            source_type=payload.source_type,
            tier=payload.tier,
            query=payload.query,
        )
        return await self.evidence.capture(
            hit,
            payload.claim,
            SupportLevel.PARTIAL if payload.adversarial else SupportLevel.DIRECT,
        )

    async def fetch_filing(self, payload: DocumentFilingPayload) -> dict[str, object]:
        snapshot = await self.sec.latest_filing(payload.cik_or_ticker, payload.form)
        return snapshot.model_dump(mode="json")
