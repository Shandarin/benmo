from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from benmo_worker.errors import PermanentTaskError, RetryableTaskError
from benmo_worker.logging import bind_context, clear_context, get_logger
from benmo_worker.ports import WorkerRepository
from benmo_worker.schemas import StrictModel, TaskMessage, TaskType

TaskHandler = Callable[[TaskMessage], Awaitable[StrictModel | dict[str, Any]]]


class SqsDispatcher:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def send(self, queue_url: str, task: TaskMessage) -> str:
        kwargs: dict[str, Any] = {
            "QueueUrl": queue_url,
            "MessageBody": task.model_dump_json(),
            "MessageAttributes": {
                "task_type": {"DataType": "String", "StringValue": task.task_type.value},
                "idempotency_key": {"DataType": "String", "StringValue": task.idempotency_key},
            },
        }
        if queue_url.endswith(".fifo"):
            kwargs["MessageGroupId"] = task.entity_id
            kwargs["MessageDeduplicationId"] = task.idempotency_key
        response = await asyncio.to_thread(self.client.send_message, **kwargs)
        return str(response["MessageId"])


class SqsConsumer:
    def __init__(
        self,
        *,
        client: Any,
        queue_urls: list[str],
        repository: WorkerRepository,
        handler: TaskHandler,
        accepted_types: set[TaskType],
        wait_seconds: int = 20,
        visibility_timeout: int = 900,
        max_messages: int = 1,
    ) -> None:
        if not queue_urls:
            raise ValueError("at least one queue URL is required")
        self.client = client
        self.queue_urls = queue_urls
        self.repository = repository
        self.handler = handler
        self.accepted_types = accepted_types
        self.wait_seconds = wait_seconds
        self.visibility_timeout = visibility_timeout
        self.max_messages = max_messages
        self.log = get_logger("benmo_worker.queue")

    async def consume(self, *, once: bool = False) -> int:
        processed = 0
        while True:
            found = False
            for queue_url in self.queue_urls:
                messages = await self._receive(queue_url)
                if messages:
                    found = True
                for message in messages:
                    await self._process(queue_url, message)
                    processed += 1
            if once:
                return processed
            if not found and self.wait_seconds == 0:
                await asyncio.sleep(0.25)

    async def _receive(self, queue_url: str) -> list[dict[str, Any]]:
        response = await asyncio.to_thread(
            self.client.receive_message,
            QueueUrl=queue_url,
            MaxNumberOfMessages=self.max_messages,
            WaitTimeSeconds=self.wait_seconds,
            VisibilityTimeout=self.visibility_timeout,
            MessageSystemAttributeNames=["ApproximateReceiveCount"],
            MessageAttributeNames=["All"],
        )
        return list(response.get("Messages", []))

    async def _process(self, queue_url: str, message: dict[str, Any]) -> None:
        receipt = message["ReceiptHandle"]
        receive_count = int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
        try:
            task = TaskMessage.model_validate_json(message["Body"])
        except ValidationError as exc:
            self.log.error(
                "discarding invalid task envelope",
                fields={"queue_url": queue_url, "receive_count": receive_count, "error": str(exc)},
            )
            await self._delete(queue_url, receipt)
            return
        bind_context(task_id=str(task.task_id), task_type=task.task_type.value, entity_id=task.entity_id)
        try:
            if task.task_type not in self.accepted_types:
                raise PermanentTaskError(f"{task.task_type} cannot be processed by this worker ({self.accepted_types})")
            claim = await self.repository.claim(task)
            if not claim.claimed:
                self.log.info("task already claimed or completed; acknowledging duplicate")
                await self._delete(queue_url, receipt)
                return
            result = await self._with_heartbeat(queue_url, receipt, self.handler(task))
            payload = result.model_dump(mode="json") if isinstance(result, StrictModel) else result
            await self.repository.complete(task, payload)
            await self._delete(queue_url, receipt)
            self.log.info("task completed", fields={"receive_count": receive_count})
        except PermanentTaskError as exc:
            await self.repository.fail(task, str(exc), retryable=False)
            await self._delete(queue_url, receipt)
            self.log.error("permanent task failure", fields={"error": str(exc)})
        except (RetryableTaskError, Exception) as exc:
            await self.repository.fail(task, str(exc), retryable=True)
            delay = min(self.visibility_timeout, 30 * (2 ** min(receive_count - 1, 7)))
            await asyncio.to_thread(
                self.client.change_message_visibility,
                QueueUrl=queue_url,
                ReceiptHandle=receipt,
                VisibilityTimeout=delay,
            )
            self.log.exception(
                "retryable task failure; message left for SQS redrive",
                fields={"error": str(exc), "receive_count": receive_count, "retry_delay": delay},
            )
        finally:
            clear_context()

    async def _with_heartbeat(
        self, queue_url: str, receipt: str, operation: Awaitable[StrictModel | dict[str, Any]]
    ) -> StrictModel | dict[str, Any]:
        task: asyncio.Future[StrictModel | dict[str, Any]] = asyncio.ensure_future(operation)
        interval = max(15, min(60, self.visibility_timeout // 2))
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=interval)
                if done:
                    return task.result()
                await asyncio.to_thread(
                    self.client.change_message_visibility,
                    QueueUrl=queue_url,
                    ReceiptHandle=receipt,
                    VisibilityTimeout=self.visibility_timeout,
                )
        finally:
            if not task.done():
                task.cancel()

    async def _delete(self, queue_url: str, receipt: str) -> None:
        await asyncio.to_thread(self.client.delete_message, QueueUrl=queue_url, ReceiptHandle=receipt)
