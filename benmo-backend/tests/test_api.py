from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx

from benmo_backend.queueing.memory import MemoryTaskQueue


async def _submit(client: httpx.AsyncClient, key: str = "request-0000000001") -> dict[str, str]:
    response = await client.post(
        "/v1/analyses",
        headers={"Idempotency-Key": key},
        json={"input_text": "Oil rose 10%; which airline costs could be affected?"},
    )
    assert response.status_code == 202, response.text
    return response.json()


async def test_analysis_submit_is_idempotent_and_sse_is_replayable(client, app) -> None:  # type: ignore[no-untyped-def]
    first = await _submit(client)
    second = await _submit(client)
    assert second == first
    assert first["status"] == "queued"

    queue: MemoryTaskQueue = app.state.task_queue
    assert queue.messages.qsize() == 1
    message = await queue.messages.get()
    assert message.entity_id == first["analysis_id"]
    assert message.task_type == "analysis.research"

    from benmo_worker.schemas import TaskMessage as WorkerTaskMessage

    parsed = WorkerTaskMessage.model_validate_json(message.wire_json())
    assert str(parsed.task_id) == str(message.task_id)
    assert parsed.idempotency_key == message.idempotency_key

    detail = await client.get(f"/v1/analyses/{first['analysis_id']}")
    assert detail.status_code == 200
    assert detail.json()["current_stage"] == "queued"

    stream = await client.get(f"/v1/analyses/{first['analysis_id']}/events?follow=false")
    assert stream.status_code == 200
    assert "event: analysis.queued" in stream.text
    assert "event: end" in stream.text


async def test_idempotency_key_conflict(client) -> None:  # type: ignore[no-untyped-def]
    await _submit(client, "request-conflict-0001")
    response = await client.post(
        "/v1/analyses",
        headers={"Idempotency-Key": "request-conflict-0001"},
        json={"input_text": "A materially different event description for the same key."},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_worker_claim_progress_and_complete_contract(client, app, worker_token) -> None:  # type: ignore[no-untyped-def]
    accepted = await _submit(client, "request-worker-flow-0001")
    analysis_id = accepted["analysis_id"]
    unpublished = await client.get(
        accepted["public_url"].replace("/analysis/", "/v1/public/analyses/")
    )
    assert unpublished.status_code == 404
    queue: MemoryTaskQueue = app.state.task_queue
    message = await queue.messages.get()
    headers = {"X-Benmo-Worker-Token": worker_token}

    claim_payload = {
        "idempotency_key": message.idempotency_key,
        "task_type": message.task_type,
        "entity_id": message.entity_id,
        "workflow_version": message.workflow_version,
    }
    claim = await client.post(
        f"/v1/internal/worker/tasks/{message.task_id}/claim",
        headers=headers,
        json=claim_payload,
    )
    assert claim.status_code == 200, claim.text
    assert claim.json() == {"claimed": True, "previous_result": None}
    replay = await client.post(
        f"/v1/internal/worker/tasks/{message.task_id}/claim",
        headers=headers,
        json=claim_payload,
    )
    assert replay.json()["claimed"] is False

    progress = await client.post(
        f"/v1/internal/worker/tasks/{message.task_id}/progress",
        headers=headers,
        json={
            "stage": "evidence_research",
            "details": {"progress_percent": 40, "message": "Checking sources"},
            "occurred_at": datetime.now(UTC).isoformat(),
        },
    )
    assert progress.status_code == 204, progress.text

    outcome = _worker_outcome(analysis_id)
    completed = await client.post(
        f"/v1/internal/analyses/{analysis_id}/complete",
        headers=headers,
        json=outcome.model_dump(mode="json"),
    )
    assert completed.status_code == 200, completed.text
    completion = completed.json()
    assert completion["status"] == "published"
    assert completion["idempotent_replay"] is False

    replay_completion = await client.post(
        f"/v1/internal/analyses/{analysis_id}/complete",
        headers=headers,
        json=outcome.model_dump(mode="json"),
    )
    assert replay_completion.status_code == 200, replay_completion.text
    assert replay_completion.json()["idempotent_replay"] is True

    detail = await client.get(f"/v1/analyses/{analysis_id}")
    assert detail.json()["status"] == "published"
    chains = await client.get("/v1/chains")
    assert len(chains.json()) == 1
    chain_id = chains.json()[0]["id"]
    graph = await client.get(f"/v1/chains/{chain_id}/graph")
    assert graph.status_code == 200, graph.text
    assert len(graph.json()["nodes"]) == 2
    assert len(graph.json()["edges"]) == 1
    edge_id = graph.json()["edges"][0]["id"]
    evidence = await client.get(f"/v1/edges/{edge_id}/evidence")
    assert evidence.status_code == 200
    assert evidence.json()[0]["span"]["quote_verified"] is True
    history = await client.get(f"/v1/verification/edges/{edge_id}")
    assert history.status_code == 200
    assert len(history.json()["specs"]) == 1
    public_list = await client.get("/v1/public/analyses")
    assert public_list.status_code == 200
    assert public_list.json()[0]["public_slug"] in accepted["public_url"]
    public_detail = await client.get(
        accepted["public_url"].replace("/analysis/", "/v1/public/analyses/")
    )
    assert public_detail.status_code == 200, public_detail.text
    assert public_detail.json()["event"]["title"] == "Oil prices increased materially."
    assert public_detail.json()["graph"]["version"].get("snapshot") is None
    assert public_detail.json()["evidence_by_edge"][edge_id][0]["span"].get("content_hash") is None


async def test_review_decision_updates_analysis_and_public_visibility(
    client, app, worker_token
) -> None:  # type: ignore[no-untyped-def]
    from benmo_worker.schemas import GateAction

    accepted = await _submit(client, "request-review-flow-0001")
    analysis_id = accepted["analysis_id"]
    queue: MemoryTaskQueue = app.state.task_queue
    await queue.messages.get()
    outcome = _worker_outcome(analysis_id).model_copy(update={"action": GateAction.REVIEW})
    completion = await client.post(
        f"/v1/internal/analyses/{analysis_id}/complete",
        headers={"X-Benmo-Worker-Token": worker_token},
        json=outcome.model_dump(mode="json"),
    )
    assert completion.status_code == 200, completion.text
    assert completion.json()["status"] == "review_required"
    public_url = accepted["public_url"].replace("/analysis/", "/v1/public/analyses/")
    assert (await client.get(public_url)).status_code == 404

    reviews = await client.get(
        "/v1/admin/reviews",
        headers={"X-Admin-Key": "test-admin-key"},
    )
    assert reviews.status_code == 200
    review_id = reviews.json()[0]["id"]
    decision = await client.post(
        f"/v1/admin/reviews/{review_id}/decision",
        headers={"X-Admin-Key": "test-admin-key"},
        json={
            "decision": "approved",
            "reviewer_id": "test-reviewer",
            "notes": "Evidence is sufficient for publication.",
        },
    )
    assert decision.status_code == 200, decision.text
    analysis = await client.get(f"/v1/analyses/{analysis_id}")
    assert analysis.json()["status"] == "published"
    assert (await client.get(public_url)).status_code == 200
    progress = await client.get(f"/v1/analyses/{analysis_id}/events?follow=false")
    assert "analysis.review_decided" in progress.text


async def test_review_rejection_keeps_analysis_private(client, app, worker_token) -> None:  # type: ignore[no-untyped-def]
    from benmo_worker.schemas import GateAction

    accepted = await _submit(client, "request-review-rejection-0001")
    analysis_id = accepted["analysis_id"]
    queue: MemoryTaskQueue = app.state.task_queue
    await queue.messages.get()
    outcome = _worker_outcome(analysis_id).model_copy(update={"action": GateAction.REVIEW})
    completion = await client.post(
        f"/v1/internal/analyses/{analysis_id}/complete",
        headers={"X-Benmo-Worker-Token": worker_token},
        json=outcome.model_dump(mode="json"),
    )
    assert completion.status_code == 200, completion.text
    reviews = await client.get(
        "/v1/admin/reviews",
        headers={"X-Admin-Key": "test-admin-key"},
    )
    review_id = reviews.json()[0]["id"]
    decision = await client.post(
        f"/v1/admin/reviews/{review_id}/decision",
        headers={"X-Admin-Key": "test-admin-key"},
        json={
            "decision": "rejected",
            "reviewer_id": "test-reviewer",
            "notes": "The evidence does not support publication.",
        },
    )
    assert decision.status_code == 200, decision.text
    analysis = await client.get(f"/v1/analyses/{analysis_id}")
    assert analysis.json()["status"] == "rejected"
    public_url = accepted["public_url"].replace("/analysis/", "/v1/public/analyses/")
    assert (await client.get(public_url)).status_code == 404


async def test_internal_routes_require_worker_token(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        f"/v1/internal/analyses/{uuid.uuid4()}/fail",
        json={"error_code": "x", "error_message": "not authorized"},
    )
    assert response.status_code == 403


async def test_real_worker_closes_api_queue_loop(client, app, worker_token, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from benmo_worker.app import build_application
    from benmo_worker.backend import HttpBackendClient
    from benmo_worker.config import Settings as WorkerSettings
    from benmo_worker.schemas import TaskMessage as WorkerTaskMessage

    accepted = await _submit(client, "request-real-worker-0001")
    queue: MemoryTaskQueue = app.state.task_queue
    queued = await queue.messages.get()
    task = WorkerTaskMessage.model_validate_json(queued.wire_json())

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Benmo-Worker-Token": worker_token},
    ) as internal_http:
        backend = HttpBackendClient(
            "http://test",
            worker_token,
            client=internal_http,
        )
        worker = build_application(
            WorkerSettings(
                env="test",
                provider_mode="stub",
                local_object_path=tmp_path / "objects",
                local_state_path=tmp_path / "worker.sqlite3",
            )
        )
        worker.dependencies.repository = backend

        claim = await backend.claim(task)
        assert claim.claimed is True
        outcome = await worker.handle_research(task)
        await backend.complete(task, outcome.model_dump(mode="json"))

    detail = await client.get(f"/v1/analyses/{accepted['analysis_id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "published"
    chains = await client.get("/v1/chains")
    assert len(chains.json()) == 1
    graph = await client.get(f"/v1/chains/{chains.json()[0]['id']}/graph")
    assert graph.status_code == 200
    assert len(graph.json()["edges"]) == 2


async def test_model_run_audit_is_immutable(client, app, worker_token) -> None:  # type: ignore[no-untyped-def]
    from benmo_backend.models import ModelRun

    run_id = uuid.uuid4()
    now = datetime.now(UTC)
    payload = {
        "run_id": str(run_id),
        "provider": "openai",
        "model": "test-model",
        "purpose": "candidate_edge_generation",
        "prompt_template_version": "candidate-edge-v1",
        "input_hash": "a" * 64,
        "output_hash": "b" * 64,
        "raw_response_storage_key": f"model-runs/{run_id}/raw-response.json",
        "structured_output": {"edges": []},
        "input_tokens": 10,
        "output_tokens": 5,
        "search_count": 0,
        "latency_ms": 25,
        "started_at": now.isoformat(),
        "completed_at": now.isoformat(),
        "status": "success",
    }
    headers = {"X-Benmo-Worker-Token": worker_token}

    created = await client.post("/v1/internal/model-runs", headers=headers, json=payload)
    replay = await client.post("/v1/internal/model-runs", headers=headers, json=payload)
    assert created.status_code == 204
    assert replay.status_code == 204

    async with app.state.session_factory() as session:
        stored = await session.get(ModelRun, run_id)
        assert stored is not None
        assert stored.prompt_template_version == "candidate-edge-v1"
        assert stored.input_tokens == 10

    changed = {**payload, "output_hash": "c" * 64}
    conflict = await client.post("/v1/internal/model-runs", headers=headers, json=changed)
    assert conflict.status_code == 409


def _worker_outcome(analysis_id: str):  # type: ignore[no-untyped-def]
    from benmo_worker.schemas import (
        AnalysisOutcome,
        AtomicFact,
        BaselineRule,
        CandidateEdge,
        ChainVersion,
        ComparatorOperation,
        ConfidenceGrade,
        ContradictionLevel,
        Direction,
        EdgeResearchResult,
        EntailmentLabel,
        EntailmentResult,
        EvaluatedEvidence,
        EvidenceSpan,
        EvidenceStatus,
        ExpectedDirection,
        FactStatus,
        GateAction,
        NodeType,
        NormalizedEvent,
        ObservationWindow,
        PublicationGateDecision,
        RelationType,
        SourceTier,
        SourceType,
        SupportLevel,
        TimeScale,
        VerificationSpec,
        content_sha256,
    )

    now = datetime.now(UTC)
    external_edge_id = "edge_test_oil_to_cost"
    quote = "Fuel prices are a material component of airline operating expense."
    evidence = EvaluatedEvidence(
        span=EvidenceSpan(
            evidence_id="ev_test_primary",
            source_id="src_test_primary",
            source_url="https://example.com/filing",
            source_type=SourceType.SEC_10K,
            tier=SourceTier.A,
            publisher="Example Airline",
            published_at=now - timedelta(days=30),
            retrieved_at=now,
            quoted_span=quote,
            start_offset=10,
            end_offset=10 + len(quote),
            snapshot_hash=content_sha256("snapshot containing the quote"),
            quote_hash=content_sha256(quote),
            supported_claim="Fuel prices affect airline operating costs.",
            support_level=SupportLevel.DIRECT,
            independent_source_key="sec:example-airline",
        ),
        entailment=EntailmentResult(
            label=EntailmentLabel.DIRECT,
            rationale="The filing directly identifies fuel as an operating cost.",
            provider="deterministic-test",
        ),
    )
    edge = CandidateEdge(
        edge_id=external_edge_id,
        from_node="Jet fuel price rises",
        to_node="Airline unit fuel cost rises",
        from_node_type=NodeType.COMMODITY,
        to_node_type=NodeType.COMPANY_METRIC,
        relation_type=RelationType.INPUT_COST,
        direction=Direction.POSITIVE,
        mechanism="Higher unhedged jet fuel prices increase airline fuel expense.",
        conditions=["Hedge coverage does not fully offset spot prices."],
        invalidation_conditions=["The airline is fully hedged for the observation window."],
        evidence_search_queries=["airline fuel expense annual report"],
        verification_metric="airline.fuel_cost_per_asm",
        source_adapter="sec_xbrl",
        time_scale=TimeScale.NEXT_QUARTER,
        ticker="TEST",
    )
    spec = VerificationSpec(
        spec_id="spec_test_fuel_cost",
        edge_id=external_edge_id,
        metric_code="airline.fuel_cost_per_asm",
        source_adapter="sec_xbrl",
        expected_direction=ExpectedDirection.INCREASE,
        threshold=3,
        baseline_rule=BaselineRule.PREVIOUS_OBSERVATION,
        observation_window=ObservationWindow(
            start=now + timedelta(days=1), end=now + timedelta(days=90)
        ),
        comparator=ComparatorOperation.CHANGE_PCT_GTE,
        locked_at=now,
    ).with_hash()
    gate = PublicationGateDecision(
        edge_id=external_edge_id,
        action=GateAction.PUBLISH,
        evidence_status=EvidenceStatus.SUPPORTED,
        confidence_grade=ConfidenceGrade.A,
        reasons=["Direct primary evidence and an executable indicator are present."],
        direct_support_count=1,
        primary_source_count=1,
        independent_secondary_count=0,
        contradiction_level=ContradictionLevel.NONE,
        ticker_removed=False,
    )
    chain = ChainVersion(
        chain_id="chain_test_oil_airline",
        version=1,
        analysis_id=analysis_id,
        event=NormalizedEvent(
            analysis_id=analysis_id,
            claimed_event="Oil prices increased materially.",
            observed_facts=[
                AtomicFact(
                    subject="WTI crude",
                    metric="WTI",
                    value=110,
                    unit="USD/bbl",
                    change_pct=10,
                    period="5 trading days",
                    observed_at=now,
                    status=FactStatus.VERIFIED,
                )
            ],
            unverified_claims=["The price move was caused by a geopolitical event."],
            normalized_at=now,
        ),
        edges=[EdgeResearchResult(edge=edge, supporting=[evidence])],
        verification_specs=[spec],
        gate_decisions=[gate],
        created_at=now,
        workflow_version="analysis-v1",
    ).immutable()
    return AnalysisOutcome(
        analysis_id=analysis_id,
        action=GateAction.PUBLISH,
        chain_version=chain,
    )
