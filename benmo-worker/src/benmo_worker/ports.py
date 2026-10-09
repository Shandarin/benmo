from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from benmo_worker.schemas import (
    AnalysisOutcome,
    CandidateGraph,
    DocumentSnapshot,
    EntailmentResult,
    ModelRunRecord,
    NormalizedEvent,
    Observation,
    SearchResultBundle,
    TaskClaim,
    TaskMessage,
    VerificationSpec,
)


@runtime_checkable
class ReasoningProvider(Protocol):
    async def normalize_event(self, analysis_id: str, query: str) -> NormalizedEvent: ...

    async def generate_candidate_graph(self, event: NormalizedEvent) -> CandidateGraph: ...


@runtime_checkable
class ResearchProvider(Protocol):
    async def search(
        self,
        query: str,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
    ) -> SearchResultBundle: ...


@runtime_checkable
class EntailmentProvider(Protocol):
    async def verify_support(self, claim: str, evidence_span: str) -> EntailmentResult: ...


@runtime_checkable
class DocumentProvider(Protocol):
    async def fetch(self, url: str) -> DocumentSnapshot: ...


@runtime_checkable
class NewsProvider(Protocol):
    async def company_news(self, symbol: str, start: datetime, end: datetime) -> SearchResultBundle: ...


@runtime_checkable
class SECProvider(Protocol):
    async def latest_filing(self, cik_or_ticker: str, form: str) -> DocumentSnapshot: ...


@runtime_checkable
class TranscriptProvider(Protocol):
    async def latest_transcript(self, ticker: str) -> DocumentSnapshot: ...


@runtime_checkable
class FinancialProvider(Protocol):
    async def financial_observation(self, metric_code: str, at: datetime) -> Observation: ...


@runtime_checkable
class CommodityProvider(Protocol):
    async def commodity_observation(self, metric_code: str, at: datetime) -> Observation: ...


@runtime_checkable
class MacroProvider(Protocol):
    async def macro_observation(self, metric_code: str, at: datetime) -> Observation: ...


@runtime_checkable
class EntityProvider(Protocol):
    async def resolve_company(self, query: str) -> dict[str, str]: ...


@runtime_checkable
class MarketPriceProvider(Protocol):
    async def market_observation(self, metric_code: str, at: datetime) -> Observation: ...


@runtime_checkable
class IndicatorAdapter(Protocol):
    async def fetch(self, spec: VerificationSpec, observation_time: datetime) -> Observation: ...


@runtime_checkable
class ObjectStore(Protocol):
    async def put_immutable(
        self, key: str, body: bytes, content_type: str, metadata: dict[str, str] | None = None
    ) -> str: ...

    async def get(self, key: str) -> bytes: ...


@runtime_checkable
class WorkerRepository(Protocol):
    async def claim(self, task: TaskMessage) -> TaskClaim: ...

    async def progress(self, task: TaskMessage, stage: str, details: dict[str, Any]) -> None: ...

    async def complete(self, task: TaskMessage, result: dict[str, Any]) -> None: ...

    async def fail(self, task: TaskMessage, error: str, retryable: bool) -> None: ...

    async def persist_analysis(self, outcome: AnalysisOutcome) -> None: ...

    async def persist_model_run(self, record: ModelRunRecord) -> None: ...


@runtime_checkable
class TaskDispatcher(Protocol):
    async def send(self, queue_url: str, task: TaskMessage) -> str: ...
