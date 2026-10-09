from __future__ import annotations

from dataclasses import dataclass

from benmo_worker.schemas import NodeType, RelationType


@dataclass(frozen=True, slots=True)
class RelationRule:
    relation_type: RelationType
    allowed_from: frozenset[NodeType]
    allowed_to: frozenset[NodeType]
    required_evidence: tuple[str, ...]
    suggested_adapters: tuple[str, ...]
    default_window_days: int
    human_review_conditions: tuple[str, ...]


TAXONOMY_VERSION = "causal-taxonomy-v1"

RELATION_RULES: dict[RelationType, RelationRule] = {
    RelationType.INPUT_COST: RelationRule(
        RelationType.INPUT_COST,
        frozenset({NodeType.COMMODITY, NodeType.COMPANY_METRIC}),
        frozenset({NodeType.INDUSTRY, NodeType.COMPANY, NodeType.COMPANY_METRIC}),
        ("direct cost disclosure", "input price linkage"),
        ("commodity", "financials", "sec"),
        120,
        ("material hedge", "long-term fixed contract"),
    ),
    RelationType.SELLING_PRICE: RelationRule(
        RelationType.SELLING_PRICE,
        frozenset({NodeType.COMMODITY, NodeType.INVENTORY, NodeType.CAPACITY}),
        frozenset({NodeType.INDUSTRY, NodeType.COMPANY_METRIC, NodeType.MARKET_PRICE}),
        ("realized price disclosure", "pricing mechanism"),
        ("commodity", "financials"),
        45,
        ("regulated price", "fixed-price contract"),
    ),
    RelationType.DEMAND: RelationRule(
        RelationType.DEMAND,
        frozenset({NodeType.MACRO, NodeType.COMPANY_METRIC, NodeType.EVENT}),
        frozenset({NodeType.INDUSTRY, NodeType.COMPANY_METRIC, NodeType.COMPANY}),
        ("volume or order evidence",),
        ("macro", "financials", "transcript"),
        180,
        ("substitution", "inventory buffering"),
    ),
    RelationType.SUPPLY: RelationRule(
        RelationType.SUPPLY,
        frozenset({NodeType.CAPACITY, NodeType.INVENTORY, NodeType.EVENT}),
        frozenset({NodeType.INDUSTRY, NodeType.MARKET_PRICE, NodeType.COMPANY_METRIC}),
        ("capacity or inventory observation",),
        ("commodity", "official"),
        30,
        ("spare capacity", "import substitution"),
    ),
    RelationType.FINANCING_COST: RelationRule(
        RelationType.FINANCING_COST,
        frozenset({NodeType.MACRO}),
        frozenset({NodeType.COMPANY_METRIC, NodeType.INDUSTRY}),
        ("debt structure disclosure", "benchmark rate linkage"),
        ("macro", "sec", "financials"),
        180,
        ("fixed-rate debt", "interest-rate hedge"),
    ),
    RelationType.CURRENCY_TRANSLATION: RelationRule(
        RelationType.CURRENCY_TRANSLATION,
        frozenset({NodeType.MACRO, NodeType.MARKET_PRICE}),
        frozenset({NodeType.COMPANY_METRIC, NodeType.COMPANY}),
        ("geographic revenue", "currency sensitivity"),
        ("market_price", "sec"),
        120,
        ("currency hedge", "natural hedge"),
    ),
    RelationType.REGULATORY_COST: RelationRule(
        RelationType.REGULATORY_COST,
        frozenset({NodeType.REGULATION}),
        frozenset({NodeType.INDUSTRY, NodeType.COMPANY_METRIC, NodeType.COMPANY}),
        ("rule text", "compliance cost disclosure"),
        ("web_search", "sec"),
        365,
        ("rule stayed", "company exempt"),
    ),
    RelationType.INVENTORY_PRICE_PRESSURE: RelationRule(
        RelationType.INVENTORY_PRICE_PRESSURE,
        frozenset({NodeType.INVENTORY}),
        frozenset({NodeType.MARKET_PRICE, NodeType.INDUSTRY}),
        ("official inventory series", "price series"),
        ("commodity", "official"),
        30,
        ("seasonality", "unreported storage"),
    ),
    RelationType.CAPACITY_DISRUPTION: RelationRule(
        RelationType.CAPACITY_DISRUPTION,
        frozenset({NodeType.CAPACITY, NodeType.EVENT}),
        frozenset({NodeType.INDUSTRY, NodeType.MARKET_PRICE}),
        ("facility status", "capacity magnitude"),
        ("news", "official"),
        30,
        ("rapid restart", "substitute capacity"),
    ),
    RelationType.GUIDANCE_DEMAND: RelationRule(
        RelationType.GUIDANCE_DEMAND,
        frozenset({NodeType.COMPANY, NodeType.COMPANY_METRIC}),
        frozenset({NodeType.INDUSTRY, NodeType.COMPANY, NodeType.COMPANY_METRIC}),
        ("company guidance", "customer or supplier linkage"),
        ("transcript", "sec"),
        120,
        ("guidance withdrawn", "relationship immaterial"),
    ),
}


def validate_relation(relation_type: RelationType, from_type: NodeType, to_type: NodeType) -> RelationRule:
    rule = RELATION_RULES[relation_type]
    if from_type not in rule.allowed_from:
        raise ValueError(f"{from_type} cannot originate {relation_type}")
    if to_type not in rule.allowed_to:
        raise ValueError(f"{to_type} cannot terminate {relation_type}")
    return rule
