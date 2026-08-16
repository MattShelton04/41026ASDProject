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

RUN uv sync --locked --no-dev --package student-1-feature --no-install-workspace

COPY shared/contracts/python shared/contracts/python
COPY student-1/backend/src student-1/backend/src
COPY student-1/database/src student-1/database/src
COPY student-1/config student-1/config
COPY student-1/contracts student-1/contracts
RUN uv sync --locked --no-dev --package student-1-feature && uv cache clean

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app/student-1/backend/src:/app/student-1/database/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 10001 propertyscope \
    && useradd --uid 10001 --gid propertyscope --create-home \
        --shell /usr/sbin/nologin propertyscope \
    && install -d --owner propertyscope --group propertyscope /var/lib/propertyscope/artifacts
COPY --from=builder --chown=propertyscope:propertyscope /app/.venv /app/.venv
COPY --from=builder --chown=propertyscope:propertyscope /app/shared/contracts /app/shared/contracts
COPY --from=builder --chown=propertyscope:propertyscope /app/student-1 /app/student-1
USER propertyscope

FROM runtime AS database-api
EXPOSE 5202
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=30 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5202/health/ready', timeout=2)"]
CMD ["gunicorn", "--bind=0.0.0.0:5202", "--workers=1", "--threads=4", "--timeout=180", "--graceful-timeout=30", "--access-logfile=-", "--error-logfile=-", "propertyscope_data_store.app:create_app()"]

FROM runtime AS database-loader
CMD ["python", "-m", "propertyscope_data_store.loader"]

FROM runtime AS backend
EXPOSE 5201
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=30 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5201/health/ready', timeout=2)"]
CMD ["gunicorn", "--bind=0.0.0.0:5201", "--workers=1", "--threads=4", "--timeout=180", "--graceful-timeout=30", "--access-logfile=-", "--error-logfile=-", "propertyscope_data_platform.app:create_app()"]

FROM runtime AS runner
CMD ["python", "-m", "propertyscope_data_platform.runner"]

FROM nginxinc/nginx-unprivileged:1.29.1-alpine3.22-slim AS frontend
COPY student-1/frontend /usr/share/nginx/html
COPY shared/frontend/design-system /usr/share/nginx/html/design-system
COPY student-1/frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=20 \
    CMD ["wget", "--quiet", "--tries=1", "--spider", "http://127.0.0.1:8080/"]
