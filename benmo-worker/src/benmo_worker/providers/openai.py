from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID, uuid4

from benmo_worker.errors import ConfigurationError, RetryableTaskError
from benmo_worker.ports import ObjectStore, WorkerRepository
from benmo_worker.schemas import (
    CandidateGraph,
    EntailmentResult,
    ModelRunRecord,
    NormalizedEvent,
    SearchHit,
    SearchResultBundle,
    SourceTier,
    SourceType,
    canonical_json,
    content_sha256,
)
from benmo_worker.taxonomy import RELATION_RULES, TAXONOMY_VERSION


def _load_openai() -> Any:
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise ConfigurationError("live OpenAI mode requires `pip install 'benmo-worker[openai]'`") from exc
    return AsyncOpenAI


class OpenAIProvider:
    """Responses API adapter with structured output and immutable model-run audit records."""

    def __init__(
        self,
        api_key: str,
        model: str,
        entailment_model: str | None = None,
        timeout: float = 120.0,
        client: Any | None = None,
        audit_repository: WorkerRepository | None = None,
        object_store: ObjectStore | None = None,
        prompt_template_version: str = "candidate-edge-v1",
    ) -> None:
        self.model = model
        self.entailment_model = entailment_model or model
        self.client = client or _load_openai()(api_key=api_key, timeout=timeout)
        self.audit_repository = audit_repository
        self.object_store = object_store
        self.prompt_template_version = prompt_template_version

    async def _persist_audit(
        self,
        *,
        run_id: UUID,
        model: str,
        purpose: str,
        prompt: str,
        started_at: datetime,
        started_counter: float,
        response: Any | None,
        structured_output: dict[str, Any],
        status: Literal["success", "failed"],
        error_message: str | None = None,
        search_count: int = 0,
    ) -> None:
        if self.audit_repository is None:
            return
        response_data: dict[str, Any] = {}
        raw_key: str | None = None
        if response is not None and hasattr(response, "model_dump"):
            response_data = response.model_dump(mode="json")
            if self.object_store is None:
                raise ConfigurationError("OpenAI audit persistence requires an object store")
            raw_key = f"model-runs/{run_id}/raw-response.json"
            await self.object_store.put_immutable(
                raw_key,
                canonical_json(response_data),
                "application/json",
                {"provider": "openai", "model": model, "purpose": purpose},
            )
        usage = getattr(response, "usage", None)
        record = ModelRunRecord(
            run_id=run_id,
            provider="openai",
            model=model,
            purpose=purpose,
            prompt_template_version=f"{self.prompt_template_version}:{purpose}",
            input_hash=content_sha256(prompt),
            output_hash=content_sha256(response_data) if response_data else None,
            raw_response_storage_key=raw_key,
            structured_output=structured_output,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            search_count=search_count,
            latency_ms=max(0, round((perf_counter() - started_counter) * 1000)),
            started_at=started_at,
            completed_at=datetime.now(UTC),
            status=status,
            error_message=error_message,
        )
        await self.audit_repository.persist_model_run(record)

    async def _parse(
        self,
        model: str,
        prompt: str,
        schema: type[Any],
        purpose: str,
    ) -> tuple[Any, UUID]:
        run_id = uuid4()
        started_at = datetime.now(UTC)
        started_counter = perf_counter()
        try:
            response = await self.client.responses.parse(
                model=model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Return only facts supported by the supplied input. Follow the provided schema "
                            "exactly; do not invent sources, relationship types, metrics, or ticker exposure."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                text_format=schema,
            )
        except Exception as exc:
            await self._persist_audit(
                run_id=run_id,
                model=model,
                purpose=purpose,
                prompt=prompt,
                started_at=started_at,
                started_counter=started_counter,
                response=None,
                structured_output={},
                status="failed",
                error_message=str(exc)[:4_000],
            )
            raise RetryableTaskError(f"OpenAI structured response failed: {exc}") from exc
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            await self._persist_audit(
                run_id=run_id,
                model=model,
                purpose=purpose,
                prompt=prompt,
                started_at=started_at,
                started_counter=started_counter,
                response=response,
                structured_output={},
                status="failed",
                error_message="OpenAI returned no structured output",
            )
            raise RetryableTaskError("OpenAI returned no structured output")
        structured = parsed.model_dump(mode="json") if hasattr(parsed, "model_dump") else {}
        await self._persist_audit(
            run_id=run_id,
            model=model,
            purpose=purpose,
            prompt=prompt,
            started_at=started_at,
            started_counter=started_counter,
            response=response,
            structured_output=structured,
            status="success",
        )
        return parsed, run_id

    async def normalize_event(self, analysis_id: str, query: str) -> NormalizedEvent:
        prompt = f"""Normalize this request into atomic observations and separate every causal attribution
as an unverified claim. Keep analysis_id exactly {analysis_id!r}. Never mark a requester statement as a
verified fact without a supplied primary source. Request:\n{query}"""
        parsed, _ = await self._parse(
            self.model,
            prompt,
            NormalizedEvent,
            "event_normalization",
        )
        result = NormalizedEvent.model_validate(parsed)
        if result.analysis_id != analysis_id:
            result = result.model_copy(update={"analysis_id": analysis_id})
        return result

    async def generate_candidate_graph(self, event: NormalizedEvent) -> CandidateGraph:
        taxonomy = "\n".join(
            f"- {kind.value}: {','.join(x.value for x in rule.allowed_from)} -> "
            f"{','.join(x.value for x in rule.allowed_to)}; evidence={'; '.join(rule.required_evidence)}"
            for kind, rule in RELATION_RULES.items()
        )
        prompt = f"""Generate a small candidate causal graph for the normalized event below. Use only this
taxonomy and include a verification metric for every publishable edge. Do not treat an attribution as fact.
TAXONOMY VERSION: {TAXONOMY_VERSION}
{taxonomy}
EVENT:
{event.model_dump_json(indent=2)}"""
        parsed, run_id = await self._parse(
            self.model,
            prompt,
            CandidateGraph,
            "candidate_edge_generation",
        )
        result = CandidateGraph.model_validate(parsed)
        edges = [edge.model_copy(update={"created_by_model_run_id": run_id}) for edge in result.edges]
        return result.model_copy(update={"event": event, "taxonomy_version": TAXONOMY_VERSION, "edges": edges})

    async def search(
        self,
        query: str,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
    ) -> SearchResultBundle:
        tool: dict[str, Any] = {"type": "web_search"}
        if allowed_domains:
            tool["filters"] = {"allowed_domains": allowed_domains}
        instruction = query
        if blocked_domains:
            instruction += "\nDo not use these domains: " + ", ".join(blocked_domains)
        run_id = uuid4()
        started_at = datetime.now(UTC)
        started_counter = perf_counter()
        try:
            response = await self.client.responses.create(
                model=self.model,
                tools=[tool],
                include=["web_search_call.action.sources"],
                input=instruction,
            )
        except Exception as exc:
            await self._persist_audit(
                run_id=run_id,
                model=self.model,
                purpose="web_research",
                prompt=instruction,
                started_at=started_at,
                started_counter=started_counter,
                response=None,
                structured_output={},
                status="failed",
                error_message=str(exc)[:4_000],
                search_count=1,
            )
            raise RetryableTaskError(f"OpenAI web search failed: {exc}") from exc
        dumped = response.model_dump(mode="json") if hasattr(response, "model_dump") else {}
        sources = self._collect_sources(dumped)
        blocked = {domain.casefold() for domain in (blocked_domains or [])}
        hits: list[SearchHit] = []
        output_text = getattr(response, "output_text", "") or "Search result"
        for source in sources:
            url = str(source.get("url", ""))
            if not url:
                continue
            host = (urlparse(url).hostname or "").casefold()
            if any(host == domain or host.endswith(f".{domain}") for domain in blocked):
                continue
            hits.append(
                SearchHit(
                    url=url,
                    title=str(source.get("title") or host or "Web source")[:500],
                    snippet=str(source.get("snippet") or output_text)[:20_000],
                    publisher=host or "Web source",
                    source_type=SourceType.WEB,
                    tier=SourceTier.D,
                    query=query,
                )
            )
        await self._persist_audit(
            run_id=run_id,
            model=self.model,
            purpose="web_research",
            prompt=instruction,
            started_at=started_at,
            started_counter=started_counter,
            response=response,
            structured_output={"source_urls": [str(hit.url) for hit in hits]},
            status="success",
            search_count=1,
        )
        return SearchResultBundle(query=query, hits=hits, provider=f"openai:{self.model}")

    def _collect_sources(self, value: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        if isinstance(value, dict):
            if isinstance(value.get("url"), str) and value["url"].startswith(("http://", "https://")):
                found.append(value)
            for nested in value.values():
                found.extend(self._collect_sources(nested))
        elif isinstance(value, list):
            for nested in value:
                found.extend(self._collect_sources(nested))
        unique: dict[str, dict[str, Any]] = {}
        for item in found:
            unique.setdefault(str(item["url"]), item)
        return list(unique.values())

    async def verify_support(self, claim: str, evidence_span: str) -> EntailmentResult:
        prompt = f"""Classify only whether the quoted span entails the isolated claim. The allowed labels are
directly_supports, partially_supports, does_not_support, contradicts. Do not use outside knowledge.
CLAIM:\n{claim}\nQUOTED SPAN:\n{evidence_span}"""
        parsed, _ = await self._parse(
            self.entailment_model,
            prompt,
            EntailmentResult,
            "evidence_entailment",
        )
        return EntailmentResult.model_validate(parsed)
