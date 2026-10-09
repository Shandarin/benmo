from __future__ import annotations

import sys
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from benmo_backend.queueing.base import TaskMessage
from benmo_backend.queueing.sqs import SqsTaskQueue


class FakeClient:
    def __init__(self, service: str) -> None:
        self.service = service
        self.calls: list[dict[str, Any]] = []

    def send_message(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(kwargs)
        return {"MessageId": "message-1"}

    def run_task(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"tasks": [{"taskArn": "arn:aws:ecs:us-east-1:123:task/one"}], "failures": []}

    def close(self) -> None:
        return None


@pytest.fixture
def fake_boto3(monkeypatch: pytest.MonkeyPatch) -> dict[str, FakeClient]:
    clients: dict[str, FakeClient] = {}

    def client(service: str, **_: Any) -> FakeClient:
        clients[service] = FakeClient(service)
        return clients[service]

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=client))
    return clients


def message() -> TaskMessage:
    return TaskMessage(
        task_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        entity_id="analysis-1",
        payload={"analysis_id": "analysis-1", "query": "test"},
    )


async def test_publish_starts_one_shot_research_worker(
    fake_boto3: dict[str, FakeClient],
) -> None:
    queue = SqsTaskQueue(
        "https://sqs.us-east-1.amazonaws.com/123/analysis",
        "us-east-1",
        ecs_cluster="arn:aws:ecs:us-east-1:123:cluster/benmo",
        worker_task_definition="arn:aws:ecs:us-east-1:123:task-definition/research:1",
        worker_subnet_ids=["subnet-a", "subnet-b"],
        worker_security_group_ids=["sg-worker"],
    )

    message_id = await queue.publish(message())

    assert message_id == "message-1"
    assert fake_boto3["sqs"].calls[0]["QueueUrl"].endswith("/analysis")
    run_task = fake_boto3["ecs"].calls[0]
    assert run_task["networkConfiguration"]["awsvpcConfiguration"] == {
        "subnets": ["subnet-a", "subnet-b"],
        "securityGroups": ["sg-worker"],
        "assignPublicIp": "ENABLED",
    }
    assert run_task["overrides"]["containerOverrides"][0]["command"] == [
        "consume",
        "--worker",
        "research",
        "--once",
    ]


def test_partial_ecs_launcher_configuration_is_rejected(
    fake_boto3: dict[str, FakeClient],
) -> None:
    with pytest.raises(RuntimeError, match="requires cluster"):
        SqsTaskQueue(
            "https://sqs.us-east-1.amazonaws.com/123/analysis",
            "us-east-1",
            ecs_cluster="cluster",
        )
