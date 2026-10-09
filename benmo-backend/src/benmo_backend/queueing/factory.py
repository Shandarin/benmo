from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from benmo_backend.config import Settings
from benmo_backend.queueing.base import TaskQueue
from benmo_backend.queueing.database import DatabaseTaskQueue
from benmo_backend.queueing.memory import MemoryTaskQueue
from benmo_backend.queueing.sqs import SqsTaskQueue


def build_task_queue(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> TaskQueue:
    if settings.queue_backend == "memory":
        return MemoryTaskQueue()
    if settings.queue_backend == "database":
        return DatabaseTaskQueue(session_factory)
    if not settings.sqs_analysis_queue_url:
        raise RuntimeError("BENMO_SQS_ANALYSIS_QUEUE_URL is required for the SQS backend")
    return SqsTaskQueue(
        settings.sqs_analysis_queue_url,
        settings.aws_region,
        ecs_cluster=settings.ecs_cluster,
        worker_task_definition=settings.research_worker_task_definition,
        worker_subnet_ids=settings.resolved_worker_subnet_ids,
        worker_security_group_ids=settings.resolved_worker_security_group_ids,
    )
