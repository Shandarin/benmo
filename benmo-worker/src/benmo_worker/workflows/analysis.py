from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from benmo_worker.ports import ReasoningProvider
from benmo_worker.publication import PublicationGate
from benmo_worker.schemas import (
    AnalysisOutcome,
    AnalysisRequest,
    BaselineRule,
    CandidateEdge,
    CandidateGraph,
    ChainVersion,
    ComparatorOperation,
    Direction,
    ExpectedDirection,
    GateAction,
    NormalizedEvent,
    ObservationWindow,
    PublicationGateInput,
    VerificationSpec,
    content_sha256,
)
from benmo_worker.taxonomy import RELATION_RULES, TAXONOMY_VERSION, validate_relation
from benmo_worker.workflows.research import EdgeResearchWorkflow, ProgressCallback


class AnalysisWorkflow:
    def __init__(
        self,
        reasoning: ReasoningProvider,
        edge_research: EdgeResearchWorkflow,
        publication_gate: PublicationGate,
        workflow_version: str,
    ) -> None:
        self.reasoning = reasoning
        self.edge_research = edge_research
        self.publication_gate = publication_gate
        self.workflow_version = workflow_version

    async def normalize(self, request: AnalysisRequest) -> NormalizedEvent:
        return await self.reasoning.normalize_event(request.analysis_id, request.query)

    async def candidates(self, event: NormalizedEvent) -> CandidateGraph:
        graph = await self.reasoning.generate_candidate_graph(event)
        if graph.taxonomy_version != TAXONOMY_VERSION:
            raise ValueError("candidate graph uses an unsupported taxonomy version")
        for edge in graph.edges:
            validate_relation(edge.relation_type, edge.from_node_type, edge.to_node_type)
        return graph

    def compile_spec(self, edge: CandidateEdge, event: NormalizedEvent) -> VerificationSpec | None:
        if not edge.verification_metric or not edge.source_adapter or edge.direction == Direction.MIXED:
            return None
        rule = RELATION_RULES[edge.relation_type]
        expected = ExpectedDirection.INCREASE if edge.direction == Direction.POSITIVE else ExpectedDirection.DECREASE
        comparator = (
            ComparatorOperation.CHANGE_PCT_GTE
            if edge.direction == Direction.POSITIVE
            else ComparatorOperation.CHANGE_PCT_LTE
        )
        start = event.normalized_at
        spec = VerificationSpec(
            spec_id=f"spec_{content_sha256(edge.edge_id + ':v1')[:24]}",
            edge_id=edge.edge_id,
            metric_code=edge.verification_metric,
            source_adapter=edge.source_adapter,
            expected_direction=expected,
            threshold=Decimal("3"),
            baseline_rule=BaselineRule.PREVIOUS_OBSERVATION,
            observation_window=ObservationWindow(
                start=start,
                end=start + timedelta(days=rule.default_window_days),
            ),
            comparator=comparator,
            spec_version=1,
            locked_at=start,
        )
        return spec.with_hash()

    async def run(
        self,
        request: AnalysisRequest,
        progress: ProgressCallback | None = None,
    ) -> AnalysisOutcome:
        async def report(stage: str, details: dict[str, object]) -> None:
            if progress:
                await progress(stage, details)

        await report("normalize_fact", {"analysis_id": request.analysis_id})
        event = await self.normalize(request)
        await report("generate_candidates", {"observed_fact_count": len(event.observed_facts)})
        graph = await self.candidates(event)
        await report("research_edges", {"candidate_edge_count": len(graph.edges)})
        researched = []
        for index, edge in enumerate(graph.edges, start=1):
            await report(
                "research_edge",
                {"edge_id": edge.edge_id, "index": index, "total": len(graph.edges)},
            )
            researched.append(await self.edge_research.run(edge))
        specs = [spec for item in researched if (spec := self.compile_spec(item.edge, event))]
        specs_by_edge = {spec.edge_id: spec for spec in specs}
        decisions = []
        sanitized = []
        for item in researched:
            decision = self.publication_gate.evaluate(
                PublicationGateInput(
                    edge_id=item.edge.edge_id,
                    evidence=item.supporting,
                    adversarial_evidence=item.adversarial,
                    indicator_executable=item.edge.edge_id in specs_by_edge,
                    ticker=item.edge.ticker,
                    ticker_exposure_evidence=[],
                )
            )
            decisions.append(decision)
            if decision.ticker_removed:
                item = item.model_copy(update={"edge": item.edge.model_copy(update={"ticker": None})})
            sanitized.append(item)
        await report(
            "publication_gate",
            {
                "published": sum(item.action == GateAction.PUBLISH for item in decisions),
                "review": sum(item.action == GateAction.REVIEW for item in decisions),
                "rejected": sum(item.action == GateAction.REJECT for item in decisions),
            },
        )
        if any(item.action == GateAction.REVIEW for item in decisions):
            action = GateAction.REVIEW
        elif any(item.action == GateAction.PUBLISH for item in decisions):
            action = GateAction.PUBLISH
        else:
            action = GateAction.REJECT
        chain_id = f"chain_{content_sha256(request.analysis_id)[:24]}"
        chain = ChainVersion(
            chain_id=chain_id,
            version=1,
            analysis_id=request.analysis_id,
            event=event,
            edges=sanitized,
            verification_specs=specs,
            gate_decisions=decisions,
            workflow_version=self.workflow_version,
        ).immutable()
        return AnalysisOutcome(
            analysis_id=request.analysis_id,
            action=action,
            chain_version=chain,
            rejected_edge_ids=[item.edge_id for item in decisions if item.action == GateAction.REJECT],
            review_edge_ids=[item.edge_id for item in decisions if item.action == GateAction.REVIEW],
        )
