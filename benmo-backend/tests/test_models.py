from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from benmo_backend.db import Base
from benmo_backend.models import ImmutableVerificationSpecError, VerificationSpec


async def test_locked_verification_spec_cannot_be_updated() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    # The full FK graph is intentionally not populated; SQLite accepts the insert only with
    # foreign keys disabled on this direct test engine, letting this test isolate immutability.
    async with factory() as session:
        spec = VerificationSpec(
            edge_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            metric_code="metric.v1",
            source_adapter="test",
            expected_direction="increase",
            threshold={"value": 3},
            baseline_rule={"rule": "previous"},
            observation_window={"start": "tomorrow", "end": "next_quarter"},
            comparator_expression="change_pct_gte",
            spec_version=1,
            locked_at=datetime.now(UTC),
        )
        session.add(spec)
        await session.commit()
        spec.metric_code = "metric.rewritten_after_result"
        with pytest.raises(ImmutableVerificationSpecError):
            await session.commit()
        await session.rollback()
    await engine.dispose()
