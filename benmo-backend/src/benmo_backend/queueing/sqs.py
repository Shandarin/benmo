from __future__ import annotations

import asyncio
from typing import Any

from benmo_backend.queueing.base import TaskMessage


class SqsTaskQueue:
    def __init__(
        self,
        queue_url: str,
        region: str,
        *,
        ecs_cluster: str | None = None,
        worker_task_definition: str | None = None,
        worker_subnet_ids: list[str] | None = None,
        worker_security_group_ids: list[str] | None = None,
    ) -> None:
        try:
            import boto3  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - exercised only in minimal installs
            raise RuntimeError("Install benmo-backend[aws] to use the SQS queue backend") from exc
        self._queue_url = queue_url
        self._client: Any = boto3.client("sqs", region_name=region)
        self._ecs_client: Any | None = None
        self._ecs_cluster = ecs_cluster
        self._worker_task_definition = worker_task_definition
        self._worker_subnet_ids = worker_subnet_ids or []
        self._worker_security_group_ids = worker_security_group_ids or []
        launcher_values = (
            self._ecs_cluster,
            self._worker_task_definition,
            self._worker_subnet_ids,
            self._worker_security_group_ids,
        )
        if any(launcher_values) and not all(launcher_values):
            raise RuntimeError(
                "ECS one-shot worker launch requires cluster, task definition, "
                "subnets, and security groups"
            )
        if all(launcher_values):
            self._ecs_client = boto3.client("ecs", region_name=region)

    async def publish(self, message: TaskMessage) -> str:
        # boto3 rejects None-valued FIFO arguments on standard queues.
        def sanitized_send() -> dict[str, Any]:
            kwargs: dict[str, Any] = {
                "QueueUrl": self._queue_url,
                "MessageBody": message.wire_json(),
                "MessageAttributes": {
                    "task_type": {"DataType": "String", "StringValue": message.task_type}
                },
            }
            if self._queue_url.endswith(".fifo"):
                kwargs["MessageGroupId"] = "analysis"
                kwargs["MessageDeduplicationId"] = message.idempotency_key
            response: Any = self._client.send_message(**kwargs)
            return dict(response)

        response = await asyncio.to_thread(sanitized_send)
        if self._ecs_client is not None:
            await asyncio.to_thread(self._launch_worker, message)
        return str(response["MessageId"])

    def _launch_worker(self, message: TaskMessage) -> None:
        ecs_client = self._ecs_client
        if ecs_client is None:
            raise RuntimeError("ECS worker launcher is not configured")
        response: dict[str, Any] = ecs_client.run_task(
            cluster=self._ecs_cluster,
            launchType="FARGATE",
            taskDefinition=self._worker_task_definition,
            count=1,
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": self._worker_subnet_ids,
                    "securityGroups": self._worker_security_group_ids,
                    "assignPublicIp": "ENABLED",
                }
            },
            overrides={
                "containerOverrides": [
                    {
                        "name": "research",
                        "command": ["consume", "--worker", "research", "--once"],
                    }
                ]
            },
            startedBy=f"benmo-{str(message.task_id)[:30]}",
            enableECSManagedTags=True,
            propagateTags="TASK_DEFINITION",
        )
        failures = response.get("failures", [])
        tasks = response.get("tasks", [])
        if failures or not tasks:
            raise RuntimeError(f"ECS did not start the research worker: {failures}")

    async def close(self) -> None:
        for client in (self._client, self._ecs_client):
            close = getattr(client, "close", None)
            if close is not None:
                await asyncio.to_thread(close)
