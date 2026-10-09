from __future__ import annotations

import argparse
import asyncio
import json
import sys
from enum import StrEnum
from typing import Any

from pydantic import Field, ValidationError

from benmo_worker.app import WorkerApplication, build_application
from benmo_worker.config import Settings
from benmo_worker.evidence import verify_quote_exists
from benmo_worker.logging import configure_logging
from benmo_worker.publication import PublicationGate
from benmo_worker.queue import SqsConsumer
from benmo_worker.schemas import (
    AnalysisRequest,
    CandidateEdge,
    ChainVersion,
    DocumentSnapshot,
    EvidenceSpan,
    GateAction,
    NormalizedEvent,
    PublicationGateDecision,
    PublicationGateInput,
    StrictModel,
    TaskType,
    canonical_json,
    content_sha256,
)
from benmo_worker.storage import read_uri, write_uri


class WorkerKind(StrEnum):
    RESEARCH = "research"
    DOCUMENT = "document"
    VERIFICATION = "verification"


class CitationCheckInput(StrictModel):
    snapshot: DocumentSnapshot
    span: EvidenceSpan


class EntailmentInput(StrictModel):
    claim: str = Field(min_length=1, max_length=20_000)
    evidence_span: str = Field(min_length=1, max_length=20_000)


class CompileSpecInput(StrictModel):
    edge: CandidateEdge
    event: NormalizedEvent


class PublicationSummaryInput(StrictModel):
    decisions: list[PublicationGateDecision]


def _json_value(value: Any) -> Any:
    if isinstance(value, StrictModel):
        return value.model_dump(mode="json")
    return value


async def _run_stage(app: WorkerApplication, stage: str, raw: bytes) -> StrictModel | dict[str, Any] | list[Any] | None:
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"stage input is not valid UTF-8 JSON: {exc}") from exc
    if stage == "normalize-fact":
        return await app.analysis.normalize(AnalysisRequest.model_validate(data))
    if stage == "generate-candidates":
        return await app.analysis.candidates(NormalizedEvent.model_validate(data))
    if stage == "research-edge":
        return await app.analysis.edge_research.run(CandidateEdge.model_validate(data))
    if stage == "verify-citations":
        citation_input = CitationCheckInput.model_validate(data)
        verify_quote_exists(citation_input.snapshot, citation_input.span)
        return {"valid": True, "evidence_id": citation_input.span.evidence_id}
    if stage == "entailment":
        entailment_input = EntailmentInput.model_validate(data)
        return await app.dependencies.providers.entailment.verify_support(
            entailment_input.claim, entailment_input.evidence_span
        )
    if stage == "adversarial-search":
        research_result = await app.analysis.edge_research.run(CandidateEdge.model_validate(data))
        return {
            "edge_id": research_result.edge.edge_id,
            "adversarial": [_json_value(x) for x in research_result.adversarial],
        }
    if stage == "compile-spec":
        compile_input = CompileSpecInput.model_validate(data)
        return app.analysis.compile_spec(compile_input.edge, compile_input.event)
    if stage == "publication-gate":
        return PublicationGate().evaluate(PublicationGateInput.model_validate(data))
    if stage == "create-version":
        chain_version = ChainVersion.model_validate(data)
        expected = content_sha256(chain_version.model_dump(mode="json", exclude={"content_hash"}))
        if chain_version.content_hash and chain_version.content_hash != expected:
            raise ValueError("existing chain content_hash is invalid")
        return chain_version.model_copy(update={"content_hash": expected})
    if stage == "publish-review":
        summary = PublicationSummaryInput.model_validate(data)
        if any(item.action == GateAction.REVIEW for item in summary.decisions):
            action = GateAction.REVIEW
        elif any(item.action == GateAction.PUBLISH for item in summary.decisions):
            action = GateAction.PUBLISH
        else:
            action = GateAction.REJECT
        return {
            "action": action.value,
            "publish_edge_ids": [x.edge_id for x in summary.decisions if x.action == GateAction.PUBLISH],
            "review_edge_ids": [x.edge_id for x in summary.decisions if x.action == GateAction.REVIEW],
            "reject_edge_ids": [x.edge_id for x in summary.decisions if x.action == GateAction.REJECT],
        }
    if stage == "full-analysis":
        return await app.analysis.run(AnalysisRequest.model_validate(data))
    raise ValueError(f"unknown stage: {stage}")


def _sqs_client(settings: Settings) -> Any:
    import boto3  # type: ignore[import-untyped]

    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if settings.sqs_endpoint_url:
        kwargs["endpoint_url"] = settings.sqs_endpoint_url
    return boto3.client("sqs", **kwargs)


async def _consume(settings: Settings, kind: WorkerKind, once: bool) -> int:
    client = _sqs_client(settings)
    app = build_application(settings, client)
    if kind == WorkerKind.RESEARCH:
        queue_urls = [settings.research_queue_url] if settings.research_queue_url else []
        handler = app.handle_research
        accepted = {TaskType.ANALYSIS_RESEARCH}
    elif kind == WorkerKind.DOCUMENT:
        queue_urls = settings.resolved_document_queue_urls
        handler = app.handle_document
        accepted = {TaskType.DOCUMENT_FETCH, TaskType.DOCUMENT_FILING}
    else:
        queue_urls = [settings.verification_queue_url] if settings.verification_queue_url else []
        handler = app.handle_verification
        accepted = {TaskType.VERIFICATION_RUN}
    if not queue_urls:
        raise ValueError(f"no queue URL configured for {kind.value} worker")
    consumer = SqsConsumer(
        client=client,
        queue_urls=queue_urls,
        repository=app.dependencies.repository,
        handler=handler,
        accepted_types=accepted,
        wait_seconds=settings.sqs_wait_seconds,
        visibility_timeout=settings.sqs_visibility_timeout,
        max_messages=settings.sqs_max_messages,
    )
    return await consumer.consume(once=once)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="benmo-worker")
    parser.add_argument("--version", action="version", version="benmo-worker 0.1.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    consume = subparsers.add_parser("consume", help="consume an SQS worker queue")
    consume.add_argument("--worker", choices=[item.value for item in WorkerKind], required=True)
    consume.add_argument("--once", action="store_true", help="perform one receive pass and exit")

    stage = subparsers.add_parser("run-stage", help="run a workflow stage with strict JSON I/O")
    stage.add_argument(
        "stage",
        choices=[
            "normalize-fact",
            "generate-candidates",
            "research-edge",
            "verify-citations",
            "entailment",
            "adversarial-search",
            "compile-spec",
            "publication-gate",
            "create-version",
            "publish-review",
            "full-analysis",
        ],
    )
    stage.add_argument("--input", help="-, local path, or s3://bucket/key; defaults BENMO_STAGE_INPUT")
    stage.add_argument("--output", help="-, local path, or s3://bucket/key; defaults BENMO_STAGE_OUTPUT")

    subparsers.add_parser("doctor", help="validate configuration without calling external APIs")
    return parser


async def _async_main(args: argparse.Namespace, settings: Settings) -> int:
    if args.command == "consume":
        count = await _consume(settings, WorkerKind(args.worker), args.once)
        if args.once:
            print(json.dumps({"processed": count}))
        return 0
    if args.command == "run-stage":
        app = build_application(settings)
        input_uri = args.input or settings.stage_input
        output_uri = args.output or settings.stage_output or "-"
        if not input_uri:
            raise ValueError("--input or BENMO_STAGE_INPUT is required")
        raw = await read_uri(input_uri, region=settings.aws_region)
        result = await _run_stage(app, args.stage, raw)
        payload = canonical_json(_json_value(result))
        await write_uri(output_uri, payload, region=settings.aws_region)
        return 0
    if args.command == "doctor":
        build_application(settings)
        print(
            json.dumps(
                {
                    "ok": True,
                    "env": settings.env,
                    "provider_mode": settings.provider_mode,
                    "object_store": settings.object_store,
                    "backend_configured": settings.backend_base_url is not None,
                    "queues": {
                        "research": bool(settings.research_queue_url),
                        "document": len(settings.resolved_document_queue_urls),
                        "verification": bool(settings.verification_queue_url),
                    },
                },
                ensure_ascii=False,
            )
        )
        return 0
    raise AssertionError("unhandled CLI command")


def main(argv: list[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        settings = Settings()
        configure_logging(settings.log_level, settings.log_json)
        code = asyncio.run(_async_main(args, settings))
    except (ValidationError, ValueError) as exc:
        print(f"benmo-worker: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    raise SystemExit(code)


if __name__ == "__main__":
    main()
