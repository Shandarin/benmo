from __future__ import annotations

from collections.abc import Awaitable, Callable

from benmo_worker.evidence import EvidenceProcessor
from benmo_worker.ports import ResearchProvider
from benmo_worker.schemas import (
    CandidateEdge,
    EdgeResearchResult,
    EvaluatedEvidence,
    SupportLevel,
)

ProgressCallback = Callable[[str, dict[str, object]], Awaitable[None]]


class EdgeResearchWorkflow:
    def __init__(
        self,
        research: ResearchProvider,
        evidence: EvidenceProcessor,
        *,
        max_sources_per_edge: int = 8,
    ) -> None:
        self.research = research
        self.evidence = evidence
        self.max_sources_per_edge = max_sources_per_edge

    async def run(self, edge: CandidateEdge) -> EdgeResearchResult:
        claim = f"{edge.from_node} -> {edge.to_node}: {edge.mechanism}"
        supporting: list[EvaluatedEvidence] = []
        adversarial: list[EvaluatedEvidence] = []
        unavailable: list[str] = []
        seen: set[str] = set()
        for query in edge.evidence_search_queries:
            bundle = await self.research.search(query)
            for hit in bundle.hits:
                url = str(hit.url)
                if url in seen or len(supporting) >= self.max_sources_per_edge:
                    continue
                seen.add(url)
                try:
                    supporting.append(await self.evidence.capture(hit, claim, SupportLevel.DIRECT))
                except Exception:
                    unavailable.append(url)
        skeptical_query = (
            f"adversarial counterevidence and failure conditions for: {edge.from_node} to "
            f"{edge.to_node}; {edge.mechanism}"
        )
        bundle = await self.research.search(skeptical_query)
        for hit in bundle.hits[:3]:
            url = str(hit.url)
            if url in seen:
                continue
            seen.add(url)
            try:
                adversarial.append(await self.evidence.capture(hit, claim, SupportLevel.PARTIAL))
            except Exception:
                unavailable.append(url)
        return EdgeResearchResult(
            edge=edge,
            supporting=supporting,
            adversarial=adversarial,
            unavailable_urls=list(dict.fromkeys(unavailable)),
        )
