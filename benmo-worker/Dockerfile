FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install '.[openai]'

FROM python:3.12-slim

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BENMO_PROVIDER_MODE=stub \
    BENMO_LOCAL_OBJECT_PATH=/data/objects \
    BENMO_LOCAL_STATE_PATH=/data/worker-state.sqlite3

RUN groupadd --system --gid 10001 benmo && \
    useradd --system --uid 10001 --gid benmo --home-dir /nonexistent --shell /usr/sbin/nologin benmo && \
    mkdir -p /data && chown benmo:benmo /data

COPY --from=builder /opt/venv /opt/venv
USER benmo
WORKDIR /app

ENTRYPOINT ["python", "-m", "benmo_worker.cli"]
CMD ["consume", "--worker", "research"]
