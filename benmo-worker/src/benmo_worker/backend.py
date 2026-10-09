from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx

from benmo_worker.errors import PermanentTaskError, RetryableTaskError
from benmo_worker.schemas import AnalysisOutcome, ModelRunRecord, TaskClaim, TaskMessage, utc_now


class HttpBackendClient:
    """Internal backend contract used by every queue and one-shot worker."""

    def __init__(
        self,
        base_url: str,
        token: str | None,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        headers = {"User-Agent": "benmo-worker/0.1"}
        if token:
            headers["X-Benmo-Worker-Token"] = token
        self._owned_client = client is None
        self.client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout)

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise RetryableTaskError(f"backend transport failure: {exc}") from exc
        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            raise RetryableTaskError(f"backend returned retryable status {response.status_code}: {response.text[:500]}")
        if response.status_code >= 400:
            raise PermanentTaskError(f"backend rejected worker request {response.status_code}: {response.text[:500]}")
        return response

    async def claim(self, task: TaskMessage) -> TaskClaim:
        response = await self._request(
            "POST",
            f"/v1/internal/worker/tasks/{task.task_id}/claim",
            json={
                "idempotency_key": task.idempotency_key,
                "task_type": task.task_type,
                "entity_id": task.entity_id,
                "workflow_version": task.workflow_version,
            },
        )
        return TaskClaim.model_validate(response.json())

    async def progress(self, task: TaskMessage, stage: str, details: dict[str, Any]) -> None:
        await self._request(
            "POST",
            f"/v1/internal/worker/tasks/{task.task_id}/progress",
            json={"stage": stage, "details": details, "occurred_at": utc_now().isoformat()},
        )

    async def complete(self, task: TaskMessage, result: dict[str, Any]) -> None:
        await self._request("POST", f"/v1/internal/worker/tasks/{task.task_id}/complete", json={"result": result})

    async def fail(self, task: TaskMessage, error: str, retryable: bool) -> None:
        await self._request(
            "POST",
            f"/v1/internal/worker/tasks/{task.task_id}/fail",
            json={"error": error[:4_000], "retryable": retryable},
        )

    async def persist_analysis(self, outcome: AnalysisOutcome) -> None:
        await self._request(
            "POST",
            f"/v1/internal/analyses/{outcome.analysis_id}/complete",
            json=outcome.model_dump(mode="json"),
        )

    async def persist_model_run(self, record: ModelRunRecord) -> None:
        await self._request(
            "POST",
            "/v1/internal/model-runs",
            json=record.model_dump(mode="json"),
        )

    async def aclose(self) -> None:
        if self._owned_client:
            await self.client.aclose()


class SqliteWorkerRepository:
    """Durable local idempotency/replay repository used when no backend is configured."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS task_runs (
              idempotency_key TEXT PRIMARY KEY,
              task_id TEXT NOT NULL,
              status TEXT NOT NULL,
              result_json TEXT,
              error TEXT,
              updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS model_runs (
              run_id TEXT PRIMARY KEY,
              input_hash TEXT NOT NULL,
              output_hash TEXT,
              record_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS progress_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              task_id TEXT NOT NULL,
              stage TEXT NOT NULL,
              details_json TEXT NOT NULL,
              occurred_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_results (
              analysis_id TEXT PRIMARY KEY,
              content_hash TEXT NOT NULL,
              outcome_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()
        return connection

    async def claim(self, task: TaskMessage) -> TaskClaim:
        async with self._lock:
            return await asyncio.to_thread(self._claim, task)

    def _claim(self, task: TaskMessage) -> TaskClaim:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status, result_json FROM task_runs WHERE idempotency_key = ?",
                (task.idempotency_key,),
            ).fetchone()
            if row is not None and row["status"] in {"running", "completed"}:
                result = json.loads(row["result_json"]) if row["result_json"] else None
                return TaskClaim(claimed=False, previous_result=result)
            connection.execute(
                """
                INSERT INTO task_runs(idempotency_key, task_id, status, updated_at)
                VALUES (?, ?, 'running', ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    task_id=excluded.task_id, status='running', error=NULL, updated_at=excluded.updated_at
                """,
                (task.idempotency_key, str(task.task_id), utc_now().isoformat()),
            )
            return TaskClaim(claimed=True)

    async def progress(self, task: TaskMessage, stage: str, details: dict[str, Any]) -> None:
        await asyncio.to_thread(self._progress, task, stage, details)

    def _progress(self, task: TaskMessage, stage: str, details: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO progress_events(task_id, stage, details_json, occurred_at) VALUES (?, ?, ?, ?)",
                (
                    str(task.task_id),
                    stage,
                    json.dumps(details, ensure_ascii=False, sort_keys=True),
                    utc_now().isoformat(),
                ),
            )

    async def complete(self, task: TaskMessage, result: dict[str, Any]) -> None:
        await asyncio.to_thread(self._finish, task, "completed", result, None)

    async def fail(self, task: TaskMessage, error: str, retryable: bool) -> None:
        status = "retryable_failure" if retryable else "permanent_failure"
        await asyncio.to_thread(self._finish, task, status, None, error)

    def _finish(
        self,
        task: TaskMessage,
        status: str,
        result: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE task_runs SET status=?, result_json=?, error=?, updated_at=?
                WHERE idempotency_key=?
                """,
                (
                    status,
                    json.dumps(result, ensure_ascii=False, sort_keys=True) if result else None,
                    error,
                    utc_now().isoformat(),
                    task.idempotency_key,
                ),
            )

    async def persist_analysis(self, outcome: AnalysisOutcome) -> None:
        await asyncio.to_thread(self._persist_analysis, outcome)

    def _persist_analysis(self, outcome: AnalysisOutcome) -> None:
        payload = outcome.model_dump_json()
        expected_hash = outcome.chain_version.content_hash
        if expected_hash is None:
            raise ValueError("chain version must be immutable before persistence")
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT content_hash FROM analysis_results WHERE analysis_id=?",
                (outcome.analysis_id,),
            ).fetchone()
            if existing and existing["content_hash"] != expected_hash:
                raise PermanentTaskError("analysis result is immutable and already has different content")
            connection.execute(
                """
                INSERT OR IGNORE INTO analysis_results(analysis_id, content_hash, outcome_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (outcome.analysis_id, expected_hash, payload, utc_now().isoformat()),
            )

    async def persist_model_run(self, record: ModelRunRecord) -> None:
        await asyncio.to_thread(self._persist_model_run, record)

    def _persist_model_run(self, record: ModelRunRecord) -> None:
        payload = record.model_dump_json()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT input_hash, output_hash FROM model_runs WHERE run_id=?",
                (str(record.run_id),),
            ).fetchone()
            if existing and (
                existing["input_hash"] != record.input_hash or existing["output_hash"] != record.output_hash
            ):
                raise PermanentTaskError("model run is immutable and already has different content")
            connection.execute(
                """
                INSERT OR IGNORE INTO model_runs(
                  run_id, input_hash, output_hash, record_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(record.run_id),
                    record.input_hash,
                    record.output_hash,
                    payload,
                    utc_now().isoformat(),
                ),
            )
