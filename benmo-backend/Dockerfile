FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY src ./src

RUN pip install --upgrade pip && pip install ".[aws]"

RUN addgroup --system benmo && adduser --system --ingroup benmo benmo
USER benmo

EXPOSE 8000

CMD ["uvicorn", "benmo_backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

