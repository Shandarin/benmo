from __future__ import annotations

import hashlib
import re
from datetime import datetime
from decimal import Decimal
from urllib.parse import quote, unquote, urlparse

from benmo_worker.schemas import (
    AtomicFact,
    CandidateEdge,
    CandidateGraph,
    CandidateNode,
    Direction,
    DocumentSnapshot,
    EntailmentLabel,
    EntailmentResult,
    ExpectedDirection,
    FactStatus,
    NodeType,
    NormalizedEvent,
    Observation,
    RelationType,
    SearchHit,
    SearchResultBundle,
    SourceTier,
    SourceType,
    TimeScale,
    VerificationSpec,
    content_sha256,
)
from benmo_worker.taxonomy import TAXONOMY_VERSION


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _extract_change(query: str) -> Decimal | None:
    match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", query)
    return Decimal(match.group(1)) if match else None


class DeterministicProvider:
    """Offline provider with realistic, reproducible contracts for local end-to-end runs."""

    name = "deterministic-stub-v1"

    async def normalize_event(self, analysis_id: str, query: str) -> NormalizedEvent:
        lowered = query.casefold()
        change = _extract_change(query)
        if any(term in lowered for term in ("oil", "crude", "wti", "原油", "油价")):
            subject, metric, unit = "WTI crude oil", "WTI spot price", "%"
        elif any(term in lowered for term in ("rate", "yield", "利率", "收益率")):
            subject, metric, unit = "benchmark interest rate", "policy/market rate", "%"
        elif any(term in lowered for term in ("inventory", "库存")):
            subject, metric, unit = "industry inventory", "inventory level", "%"
        else:
            subject, metric, unit = "reported event", "reported magnitude", None
        observed = AtomicFact(
            subject=subject,
            metric=metric,
            change_pct=change,
            unit=unit,
            period="as stated by requester",
            status=FactStatus.UNVERIFIED,
            source_hint="requester statement; requires source verification",
        )
        return NormalizedEvent(
            analysis_id=analysis_id,
            claimed_event=query[:500],
            observed_facts=[observed],
            unverified_claims=[f"The reported event caused the stated change: {query[:350]}"],
        )

    async def generate_candidate_graph(self, event: NormalizedEvent) -> CandidateGraph:
        lowered = event.claimed_event.casefold()
        if any(term in lowered for term in ("oil", "crude", "wti", "原油", "油价")):
            edges = [
                CandidateEdge(
                    edge_id=_stable_id("edge", event.analysis_id + ":oil-jet"),
                    from_node="WTI crude oil price",
                    to_node="jet fuel selling price",
                    from_node_type=NodeType.COMMODITY,
                    to_node_type=NodeType.MARKET_PRICE,
                    relation_type=RelationType.SELLING_PRICE,
                    direction=Direction.POSITIVE,
                    mechanism=(
                        "Crude oil is a primary refinery feedstock, so its price can pass through to "
                        "jet fuel when refining margins and regional supply do not offset the move."
                    ),
                    conditions=["refinery utilization remains within its normal range"],
                    invalidation_conditions=["jet-fuel crack spreads fall enough to offset crude"],
                    evidence_search_queries=[
                        "official jet fuel crude oil price pass through evidence",
                        "EIA jet fuel price crude refinery feedstock",
                    ],
                    verification_metric="eia:PET.EER_EPJK_PF4_RGC_DPG.W",
                    source_adapter="eia",
                    time_scale=TimeScale.WEEKS,
                ),
                CandidateEdge(
                    edge_id=_stable_id("edge", event.analysis_id + ":jet-airline"),
                    from_node="jet fuel price",
                    to_node="airline fuel cost per available seat mile",
                    from_node_type=NodeType.COMPANY_METRIC,
                    to_node_type=NodeType.COMPANY_METRIC,
                    relation_type=RelationType.INPUT_COST,
                    direction=Direction.POSITIVE,
                    mechanism=(
                        "Higher realized jet fuel prices raise airline fuel expense per unit of capacity "
                        "unless hedges, efficiency or capacity mix offset the increase."
                    ),
                    conditions=["fuel consumption is not fully hedged"],
                    invalidation_conditions=["effective hedges fix most realized fuel cost"],
                    evidence_search_queries=[
                        "airline 10-K jet fuel price fuel expense sensitivity",
                        "airline fuel cost per ASM jet fuel prices",
                    ],
                    verification_metric="financial:AIRLINE:fuel_cost_per_asm",
                    source_adapter="financials",
                    time_scale=TimeScale.NEXT_QUARTER,
                ),
            ]
        elif any(term in lowered for term in ("rate", "yield", "利率", "收益率")):
            edges = [
                CandidateEdge(
                    edge_id=_stable_id("edge", event.analysis_id + ":rate-cost"),
                    from_node="benchmark interest rate",
                    to_node="company interest expense",
                    from_node_type=NodeType.MACRO,
                    to_node_type=NodeType.COMPANY_METRIC,
                    relation_type=RelationType.FINANCING_COST,
                    direction=Direction.POSITIVE,
                    mechanism=(
                        "Floating-rate borrowings generally reprice from benchmark rates into interest expense."
                    ),
                    conditions=["the company has material floating-rate debt"],
                    invalidation_conditions=["fixed-rate debt or hedges eliminate repricing"],
                    evidence_search_queries=[
                        "company filing floating rate debt interest expense sensitivity",
                        "benchmark rate financing cost corporate debt",
                    ],
                    verification_metric="financial:COMPANY:interest_expense",
                    source_adapter="financials",
                    time_scale=TimeScale.NEXT_QUARTER,
                )
            ]
        else:
            edges = [
                CandidateEdge(
                    edge_id=_stable_id("edge", event.analysis_id + ":event-demand"),
                    from_node="reported event",
                    to_node="industry volume demand",
                    from_node_type=NodeType.EVENT,
                    to_node_type=NodeType.INDUSTRY,
                    relation_type=RelationType.DEMAND,
                    direction=Direction.MIXED,
                    mechanism=(
                        "The event may change customer activity and therefore industry volume, subject to "
                        "substitution and timing."
                    ),
                    conditions=["the affected activity is material to industry demand"],
                    invalidation_conditions=["customers substitute to unaffected activity"],
                    evidence_search_queries=[f"official evidence industry volume effect {event.claimed_event[:180]}"],
                    verification_metric="macro:industry_volume_index",
                    source_adapter="macro",
                    time_scale=TimeScale.WEEKS,
                )
            ]
        labels: dict[tuple[str, NodeType], CandidateNode] = {}
        for edge in edges:
            labels.setdefault(
                (edge.from_node, edge.from_node_type),
                CandidateNode(
                    node_id=_stable_id("node", edge.from_node),
                    label=edge.from_node,
                    node_type=edge.from_node_type,
                ),
            )
            labels.setdefault(
                (edge.to_node, edge.to_node_type),
                CandidateNode(
                    node_id=_stable_id("node", edge.to_node),
                    label=edge.to_node,
                    node_type=edge.to_node_type,
                ),
            )
        return CandidateGraph(event=event, nodes=list(labels.values()), edges=edges, taxonomy_version=TAXONOMY_VERSION)

    async def search(
        self,
        query: str,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
    ) -> SearchResultBundle:
        encoded = quote(query, safe="")
        limitation = any(
            term in query.casefold() for term in ("adversarial", "counterevidence", "failure condition", "反向", "失效")
        )
        if limitation:
            content = (
                f"Official limitation for the claim under review. {query}. The relationship can be weaker "
                "when hedging, fixed contracts, spare capacity, substitution, or timing effects are material."
            )
            hits = [
                SearchHit(
                    url=f"stub://official/limitation/{encoded}",
                    title="Official limitations and offsetting conditions",
                    snippet=content,
                    publisher="Deterministic Official Data Service",
                    source_type=SourceType.OFFICIAL_DATA,
                    tier=SourceTier.A,
                    query=query,
                )
            ]
        else:
            direct = (
                f"Direct evidence supporting the transmission claim: {query}. The disclosed mechanism "
                "links the input variable to the stated output under the documented conditions."
            )
            independent = (
                f"Independent industry evidence supports the same mechanism: {query}. Observations should "
                "still be tested against a preregistered metric and time window."
            )
            hits = [
                SearchHit(
                    url=f"stub://official/support/{encoded}",
                    title="Official mechanism disclosure",
                    snippet=direct,
                    publisher="Deterministic Official Data Service",
                    source_type=SourceType.OFFICIAL_DATA,
                    tier=SourceTier.A,
                    query=query,
                ),
                SearchHit(
                    url=f"stub://industry/support/{encoded}",
                    title="Independent industry research",
                    snippet=independent,
                    publisher="Deterministic Industry Institute",
                    source_type=SourceType.INDUSTRY,
                    tier=SourceTier.B,
                    query=query,
                ),
            ]
        return SearchResultBundle(query=query, hits=hits, provider=self.name)

    async def fetch_document(self, url: str) -> DocumentSnapshot:
        parsed = urlparse(url)
        if parsed.scheme != "stub":
            raise ValueError("deterministic document provider only accepts stub:// URLs")
        query = unquote(parsed.path.rsplit("/", 1)[-1])
        limitation = parsed.netloc == "official" and "/limitation/" in parsed.path
        if limitation:
            content = (
                f"Official limitation for the claim under review. {query}. The relationship can be weaker "
                "when hedging, fixed contracts, spare capacity, substitution, or timing effects are material."
            )
            source_type, tier, publisher = (
                SourceType.OFFICIAL_DATA,
                SourceTier.A,
                "Deterministic Official Data Service",
            )
        elif parsed.netloc == "industry":
            content = (
                f"Independent industry evidence supports the same mechanism: {query}. Observations should "
                "still be tested against a preregistered metric and time window."
            )
            source_type, tier, publisher = (
                SourceType.INDUSTRY,
                SourceTier.B,
                "Deterministic Industry Institute",
            )
        else:
            content = (
                f"Direct evidence supporting the transmission claim: {query}. The disclosed mechanism "
                "links the input variable to the stated output under the documented conditions."
            )
            source_type, tier, publisher = (
                SourceType.OFFICIAL_DATA,
                SourceTier.A,
                "Deterministic Official Data Service",
            )
        return DocumentSnapshot(
            source_id=_stable_id("src", url),
            source_url=url,
            source_type=source_type,
            tier=tier,
            publisher=publisher,
            content=content,
            content_hash=content_sha256(content),
        )

    async def verify_support(self, claim: str, evidence_span: str) -> EntailmentResult:
        lowered = evidence_span.casefold()
        if any(token in lowered for token in ("contradicts", "does not cause", "opposite direction")):
            label = EntailmentLabel.CONTRADICTS
            rationale = "The span explicitly states an opposite or absent relationship."
        elif any(token in lowered for token in ("limitation", "can be weaker", "subject to")):
            label = EntailmentLabel.PARTIAL
            rationale = "The span documents a limiting condition but does not negate the mechanism."
        elif "direct evidence" in lowered:
            label = EntailmentLabel.DIRECT
            rationale = "The span explicitly describes the claimed transmission mechanism."
        else:
            claim_terms = {term for term in re.findall(r"[a-z0-9]+", claim.casefold()) if len(term) > 3}
            evidence_terms = set(re.findall(r"[a-z0-9]+", lowered))
            overlap = len(claim_terms & evidence_terms) / max(len(claim_terms), 1)
            label = EntailmentLabel.PARTIAL if overlap >= 0.25 else EntailmentLabel.NONE
            rationale = "Lexical coverage is partial." if overlap >= 0.25 else "No direct claim support found."
        return EntailmentResult(label=label, rationale=rationale, provider=self.name)

    async def fetch_indicator(self, spec: VerificationSpec, observation_time: datetime) -> Observation:
        baseline = spec.baseline_value if spec.baseline_value is not None else Decimal("100")
        if spec.expected_direction == ExpectedDirection.INCREASE:
            observed = baseline * Decimal("1.05")
        elif spec.expected_direction == ExpectedDirection.DECREASE:
            observed = baseline * Decimal("0.95")
        else:
            observed = baseline
        return Observation(
            metric_code=spec.metric_code,
            observed_value=observed,
            baseline_value=baseline,
            observed_at=observation_time,
            source_adapter=spec.source_adapter,
            source_ref=f"stub://observation/{quote(spec.metric_code, safe='')}",
            vintage_at=observation_time,
        )

    async def company_news(self, symbol: str, start: datetime, end: datetime) -> SearchResultBundle:
        return await self.search(f"{symbol} company news between {start.date()} and {end.date()}")

    async def latest_filing(self, cik_or_ticker: str, form: str) -> DocumentSnapshot:
        return await self.fetch_document(f"stub://official/support/{quote(f'{form} filing {cik_or_ticker}')}")

    async def latest_transcript(self, ticker: str) -> DocumentSnapshot:
        return await self.fetch_document(f"stub://industry/support/{quote(f'transcript {ticker}')}")

    async def financial_observation(self, metric_code: str, at: datetime) -> Observation:
        return self._observation(metric_code, at, "financials")

    async def commodity_observation(self, metric_code: str, at: datetime) -> Observation:
        return self._observation(metric_code, at, "commodity")

    async def macro_observation(self, metric_code: str, at: datetime) -> Observation:
        return self._observation(metric_code, at, "macro")

    async def market_observation(self, metric_code: str, at: datetime) -> Observation:
        return self._observation(metric_code, at, "market_price")

    def _observation(self, metric_code: str, at: datetime, adapter: str) -> Observation:
        digest = int(hashlib.sha256(metric_code.encode()).hexdigest()[:8], 16)
        baseline = Decimal("100")
        observed = baseline + Decimal(str((digest % 1000) / 100))
        return Observation(
            metric_code=metric_code,
            observed_value=observed,
            baseline_value=baseline,
            observed_at=at,
            source_adapter=adapter,
            source_ref=f"stub://observation/{quote(metric_code, safe='')}",
            vintage_at=at,
        )

    async def resolve_company(self, query: str) -> dict[str, str]:
        symbol = re.sub(r"[^A-Z0-9]", "", query.upper())[:5] or "STUB"
        return {
            "name": query,
            "ticker": symbol,
            "cik": f"{int(content_sha256(query)[:8], 16):010d}"[-10:],
        }


class DeterministicDocumentAdapter:
    """Expose only the document-fetch contract from the offline provider."""

    def __init__(self, provider: DeterministicProvider) -> None:
        self.provider = provider

    async def fetch(self, url: str) -> DocumentSnapshot:
        return await self.provider.fetch_document(url)


class DeterministicIndicatorAdapter:
    """Expose only the indicator contract from the offline provider."""

    def __init__(self, provider: DeterministicProvider) -> None:
        self.provider = provider

    async def fetch(self, spec: VerificationSpec, observation_time: datetime) -> Observation:
        return await self.provider.fetch_indicator(spec, observation_time)
