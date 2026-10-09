from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from benmo_worker.backend import HttpBackendClient, SqliteWorkerRepository
from benmo_worker.config import Settings
from benmo_worker.errors import ConfigurationError, PermanentTaskError
from benmo_worker.ports import (
    CommodityProvider,
    DocumentProvider,
    EntailmentProvider,
    EntityProvider,
    FinancialProvider,
    IndicatorAdapter,
    MacroProvider,
    MarketPriceProvider,
    NewsProvider,
    ObjectStore,
    ReasoningProvider,
    ResearchProvider,
    TranscriptProvider,
    WorkerRepository,
)
from benmo_worker.ports import (
    SECProvider as SECPort,
)
from benmo_worker.providers.data import (
    AlphaVantageProvider,
    FinnhubNewsProvider,
    JsonApiClient,
    OfficialMacroProvider,
    SECProvider,
    SECXbrlProvider,
)
from benmo_worker.providers.deterministic import (
    DeterministicDocumentAdapter,
    DeterministicIndicatorAdapter,
    DeterministicProvider,
)
from benmo_worker.providers.http import SecureHttpDocumentProvider
from benmo_worker.providers.openai import OpenAIProvider
from benmo_worker.schemas import Observation, VerificationSpec
from benmo_worker.storage import LocalObjectStore, S3ObjectStore


class LiveIndicatorRouter:
    def __init__(
        self,
        *,
        macro: OfficialMacroProvider,
        alpha_vantage: AlphaVantageProvider | None,
        sec_xbrl: SECXbrlProvider,
    ) -> None:
        self.macro = macro
        self.alpha_vantage = alpha_vantage
        self.sec_xbrl = sec_xbrl

    async def fetch(self, spec: VerificationSpec, observation_time: datetime) -> Observation:
        adapter = spec.source_adapter.casefold()
        if adapter in {"eia", "fred", "bls", "bea", "macro", "official"}:
            metric = spec.metric_code
            if adapter != "macro" and not metric.startswith(f"{adapter}:"):
                metric = f"{adapter}:{metric}"
            return await self.macro.macro_observation(metric, observation_time)
        if adapter in {"commodity", "alpha_vantage_commodity"}:
            if self.alpha_vantage is None:
                raise ConfigurationError("ALPHA_VANTAGE_API_KEY is required for this commodity metric")
            return await self.alpha_vantage.commodity_observation(spec.metric_code, observation_time)
        if adapter in {"financials", "financial", "fiscal", "alpha_vantage_financials"}:
            if self.alpha_vantage is None:
                raise ConfigurationError("ALPHA_VANTAGE_API_KEY is required for financial verification")
            return await self.alpha_vantage.financial_observation(spec.metric_code, observation_time)
        if adapter in {"market", "market_price", "alpha_vantage_market"}:
            if self.alpha_vantage is None:
                raise ConfigurationError("ALPHA_VANTAGE_API_KEY is required for market verification")
            return await self.alpha_vantage.market_observation(spec.metric_code, observation_time)
        if adapter in {"sec_xbrl", "sec"}:
            return await self.sec_xbrl.observation(spec.metric_code, observation_time)
        raise PermanentTaskError(f"no live indicator adapter registered for {spec.source_adapter}")


@dataclass(slots=True)
class ProviderBundle:
    reasoning: ReasoningProvider
    research: ResearchProvider
    entailment: EntailmentProvider
    documents: DocumentProvider
    indicators: IndicatorAdapter
    news: NewsProvider
    sec: SECPort
    transcript: TranscriptProvider
    financials: FinancialProvider
    commodity: CommodityProvider
    macro: MacroProvider
    entity: EntityProvider
    market_price: MarketPriceProvider


@dataclass(slots=True)
class RuntimeDependencies:
    providers: ProviderBundle
    object_store: ObjectStore
    repository: WorkerRepository


def _secret(value: Any | None) -> str | None:
    return value.get_secret_value() if value is not None else None


def build_dependencies(settings: Settings) -> RuntimeDependencies:
    if settings.object_store == "s3":
        object_store: ObjectStore = S3ObjectStore(
            settings.s3_bucket or "",
            settings.s3_prefix,
            region=settings.aws_region,
        )
    else:
        object_store = LocalObjectStore(settings.local_object_path)
    if settings.backend_base_url:
        repository: WorkerRepository = HttpBackendClient(
            str(settings.backend_base_url),
            _secret(settings.backend_internal_token),
            settings.backend_timeout_seconds,
        )
    else:
        repository = SqliteWorkerRepository(settings.local_state_path)

    stub = DeterministicProvider()
    if settings.provider_mode == "stub":
        stub_documents = DeterministicDocumentAdapter(stub)
        stub_indicators = DeterministicIndicatorAdapter(stub)
        providers = ProviderBundle(
            reasoning=stub,
            research=stub,
            entailment=stub,
            documents=stub_documents,
            indicators=stub_indicators,
            news=stub,
            sec=stub,
            transcript=stub,
            financials=stub,
            commodity=stub,
            macro=stub,
            entity=stub,
            market_price=stub,
        )
        return RuntimeDependencies(providers, object_store, repository)

    openai_key = _secret(settings.openai_api_key)
    if not openai_key:
        raise ConfigurationError("OpenAI API key is required in live mode")
    openai = OpenAIProvider(
        openai_key,
        settings.openai_model,
        settings.openai_entailment_model,
        settings.openai_timeout_seconds,
        audit_repository=repository,
        object_store=object_store,
        prompt_template_version=settings.prompt_version,
    )
    documents = SecureHttpDocumentProvider(
        timeout=settings.outbound_timeout_seconds,
        max_bytes=settings.max_document_bytes,
        user_agent=settings.sec_user_agent,
    )
    api = JsonApiClient(settings.outbound_timeout_seconds)
    alpha_key = _secret(settings.alpha_vantage_api_key)
    alpha = AlphaVantageProvider(alpha_key, api, documents) if alpha_key else None
    finnhub_key = _secret(settings.finnhub_api_key)
    news: NewsProvider
    if finnhub_key:
        news = FinnhubNewsProvider(finnhub_key, api)
    elif alpha:
        news = alpha
    else:
        news = stub
    sec = SECProvider(settings.sec_user_agent, api, documents)
    sec_xbrl = SECXbrlProvider(settings.sec_user_agent, api)
    macro = OfficialMacroProvider(
        api,
        fred_api_key=_secret(settings.fred_api_key),
        bls_api_key=_secret(settings.bls_api_key),
        eia_api_key=_secret(settings.eia_api_key),
        bea_api_key=_secret(settings.bea_api_key),
    )
    indicators = LiveIndicatorRouter(macro=macro, alpha_vantage=alpha, sec_xbrl=sec_xbrl)
    providers = ProviderBundle(
        reasoning=openai,
        research=openai,
        entailment=openai,
        documents=documents,
        indicators=indicators,
        news=news,
        sec=sec,
        transcript=alpha or stub,
        financials=alpha or stub,
        commodity=alpha or macro,
        macro=macro,
        entity=alpha or stub,
        market_price=alpha or stub,
    )
    return RuntimeDependencies(providers, object_store, repository)
