# syntax=docker/dockerfile:1.7

ARG UV_VERSION=0.12.1
ARG PYTHON_VERSION=3.12.13

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim-bookworm AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY ai-services/agent-core/pyproject.toml ai-services/agent-core/pyproject.toml
COPY ai-services/ai-mode/pyproject.toml ai-services/ai-mode/pyproject.toml
COPY shared/contracts/pyproject.toml shared/contracts/pyproject.toml
COPY shared/testkit/pyproject.toml shared/testkit/pyproject.toml
COPY examples/integration-test-feature/pyproject.toml examples/integration-test-feature/pyproject.toml
COPY student-1/pyproject.toml student-1/pyproject.toml
COPY student-2/pyproject.toml student-2/pyproject.toml
COPY student-3/pyproject.toml student-3/pyproject.toml
COPY student-4/pyproject.toml student-4/pyproject.toml
COPY student-5/pyproject.toml student-5/pyproject.toml
RUN uv sync --locked --no-dev --package integration-test-feature --no-install-workspace
COPY shared/contracts/python shared/contracts/python
COPY examples/integration-test-feature/src examples/integration-test-feature/src
RUN uv sync --locked --no-dev --package integration-test-feature && uv cache clean

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 10001 feature \
    && useradd --uid 10001 --gid feature --create-home --shell /usr/sbin/nologin feature \
    && install -d --owner feature --group feature /var/lib/integration-test-feature
COPY --from=builder --chown=feature:feature /app/.venv /app/.venv
COPY --from=builder --chown=feature:feature /app/examples /app/examples
COPY --from=builder --chown=feature:feature /app/shared/contracts /app/shared/contracts
USER feature

FROM runtime AS backend
EXPOSE 5101
CMD ["gunicorn", "--bind=0.0.0.0:5101", "--workers=1", "--threads=4", "integration_test_feature.backend:create_app()"]

FROM runtime AS database
ENV INTEGRATION_TEST_DATABASE_PATH=/var/lib/integration-test-feature/records.sqlite3
EXPOSE 5102
CMD ["gunicorn", "--bind=0.0.0.0:5102", "--workers=1", "--threads=4", "integration_test_feature.database:create_app()"]

FROM nginx:1.29.1-alpine3.22-slim AS frontend
COPY examples/integration-test-feature/frontend/index.html /usr/share/nginx/html/index.html
COPY examples/integration-test-feature/frontend/app.js /usr/share/nginx/html/app.js
COPY examples/integration-test-feature/frontend/styles.css /usr/share/nginx/html/styles.css
COPY examples/integration-test-feature/frontend/nginx.conf /etc/nginx/conf.d/default.conf
