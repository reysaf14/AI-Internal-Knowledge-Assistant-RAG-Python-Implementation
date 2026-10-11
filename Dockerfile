# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.11.28 AS uv

FROM python:3.12-slim AS builder
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_PROGRESS=1
COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=container \
    DOCS_PATH=docs \
    INDEX_PATH=.runtime/index.sqlite3
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY src/ ./src/
COPY docs/ ./docs/
RUN groupadd --gid 10001 rag \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin rag \
    && install -d --owner=10001 --group=10001 /app/.runtime
USER 10001:10001
ENTRYPOINT ["python", "-m", "rag_assistant"]
CMD ["bot"]
