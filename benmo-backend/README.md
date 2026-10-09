# Benmo Backend

FastAPI modular monolith for auditable, continuously verified causal-chain hypotheses.
The API records work and enqueues it; research, retrieval, LLM, and verification work is
performed by separate workers.

## Local development

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev,aws]"
set BENMO_DATABASE_URL=sqlite+aiosqlite:///./benmo.db
set BENMO_AUTO_CREATE_SCHEMA=true
.venv/Scripts/uvicorn benmo_backend.main:app --reload
```

For PostgreSQL, run `alembic upgrade head` before starting the API. The service exposes
`GET /health/live`, `GET /health/ready`, API documentation at `/docs`, and all business
routes below `/v1`.

Queue backends are selected with `BENMO_QUEUE_BACKEND`: `sqs`, `database`, or `memory`.
`database` uses queued `workflow_runs` as a durable local outbox/worker inbox. Production
SQS uses `BENMO_SQS_ANALYSIS_QUEUE_URL` and keeps the same database audit record.

## Publication invariants

- Evidence support and observed outcome are separate states.
- Every public edge needs direct, quote-verified support and an executable verification spec.
- It also needs either a primary source or two independent secondary sources.
- A material contradiction requires human review.
- A locked verification spec cannot be updated or deleted; create the next version instead.
- Ticker endpoints without exposure evidence are excluded from publication.

