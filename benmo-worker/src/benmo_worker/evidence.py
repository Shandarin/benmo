from __future__ import annotations

import re
from urllib.parse import urlparse

from benmo_worker.errors import IntegrityError
from benmo_worker.ports import DocumentProvider, EntailmentProvider, ObjectStore
from benmo_worker.schemas import (
    DocumentSnapshot,
    EntailmentResult,
    EvaluatedEvidence,
    EvidenceSpan,
    SearchHit,
    SupportLevel,
    canonical_json,
    content_sha256,
)


def _stable_source_id(snapshot: DocumentSnapshot) -> str:
    return f"src_{content_sha256(str(snapshot.source_url) + ':' + snapshot.content_hash)[:24]}"


def select_exact_quote(content: str, claim: str, hint: str | None = None, limit: int = 2_000) -> tuple[str, int, int]:
    """Select a useful span while preserving exact source offsets."""
    if hint:
        direct = content.find(hint)
        if direct >= 0:
            return hint, direct, direct + len(hint)

    boundaries = [0]
    boundaries.extend(match.end() for match in re.finditer(r"\n\s*\n|(?<=[.!?])\s+", content))
    boundaries.append(len(content))
    terms = {term for term in re.findall(r"[\w-]+", claim.casefold()) if len(term) >= 4}
    best_start, best_end, best_score = 0, min(len(content), limit), -1
    for index in range(len(boundaries) - 1):
        start = boundaries[index]
        end = min(boundaries[min(index + 3, len(boundaries) - 1)], start + limit)
        candidate = content[start:end]
        candidate_terms = set(re.findall(r"[\w-]+", candidate.casefold()))
        score = len(terms & candidate_terms)
        if score > best_score and candidate.strip():
            best_start, best_end, best_score = start, end, score
    while best_start < best_end and content[best_start].isspace():
        best_start += 1
    while best_end > best_start and content[best_end - 1].isspace():
        best_end -= 1
    quote = content[best_start:best_end]
    if not quote:
        raise IntegrityError("snapshot contains no quotable text")
    return quote, best_start, best_end


def verify_quote_exists(snapshot: DocumentSnapshot, span: EvidenceSpan) -> None:
    if snapshot.content_hash != span.snapshot_hash:
        raise IntegrityError("evidence span references a different snapshot hash")
    actual = snapshot.content[span.start_offset : span.end_offset]
    if actual != span.quoted_span:
        raise IntegrityError("quoted span does not exist at recorded offsets")
    if content_sha256(actual) != span.quote_hash:
        raise IntegrityError("quoted span hash does not match snapshot bytes")


class EvidenceProcessor:
    def __init__(
        self,
        documents: DocumentProvider,
        entailment: EntailmentProvider,
        object_store: ObjectStore,
    ) -> None:
        self.documents = documents
        self.entailment = entailment
        self.object_store = object_store

    async def capture(
        self,
        hit: SearchHit,
        claim: str,
        support_level: SupportLevel,
    ) -> EvaluatedEvidence:
        snapshot = await self.documents.fetch(str(hit.url))
        source_id = _stable_source_id(snapshot)
        retrieved = snapshot.retrieved_at.strftime("%Y%m%dT%H%M%S.%fZ")
        object_key = f"sources/{source_id}/{retrieved}/clean.txt"
        await self.object_store.put_immutable(
            object_key,
            snapshot.content.encode("utf-8"),
            snapshot.content_type,
            {
                "source-url-sha256": content_sha256(str(snapshot.source_url)),
                "source-content-sha256": snapshot.content_hash,
            },
        )
        snapshot = snapshot.model_copy(update={"source_id": source_id, "object_key": object_key})
        metadata_key = f"sources/{source_id}/{retrieved}/metadata.json"
        await self.object_store.put_immutable(
            metadata_key,
            canonical_json(snapshot.model_dump(mode="json", exclude={"content"})),
            "application/json",
        )
        quote, start, end = select_exact_quote(snapshot.content, claim, hit.snippet)
        host = (urlparse(str(snapshot.source_url)).hostname or snapshot.publisher).casefold()
        span = EvidenceSpan(
            source_id=source_id,
            source_url=snapshot.source_url,
            source_type=snapshot.source_type,
            tier=snapshot.tier,
            publisher=snapshot.publisher,
            published_at=snapshot.published_at or hit.published_at,
            retrieved_at=snapshot.retrieved_at,
            quoted_span=quote,
            start_offset=start,
            end_offset=end,
            snapshot_hash=snapshot.content_hash,
            snapshot_object_key=snapshot.object_key,
            snapshot_content_type=snapshot.content_type,
            quote_hash=content_sha256(quote),
            supported_claim=claim,
            support_level=support_level,
            limitations=[],
            independent_source_key=host,
        )
        verify_quote_exists(snapshot, span)
        result: EntailmentResult = await self.entailment.verify_support(claim, quote)
        return EvaluatedEvidence(span=span, entailment=result)
