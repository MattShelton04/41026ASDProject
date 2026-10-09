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
COPY shared/consumer-protocol/pyproject.toml shared/consumer-protocol/pyproject.toml
COPY shared/contracts/pyproject.toml shared/contracts/pyproject.toml
COPY shared/testkit/pyproject.toml shared/testkit/pyproject.toml
COPY shared/tool-runtime/pyproject.toml shared/tool-runtime/pyproject.toml
COPY ai-services/mcp-server/pyproject.toml ai-services/mcp-server/pyproject.toml
COPY ai-services/rag-server/pyproject.toml ai-services/rag-server/pyproject.toml
COPY ai-services/multi-agent-server/pyproject.toml ai-services/multi-agent-server/pyproject.toml
COPY student-1/pyproject.toml student-1/pyproject.toml
COPY student-2/pyproject.toml student-2/pyproject.toml
COPY student-3/pyproject.toml student-3/pyproject.toml
COPY student-4/pyproject.toml student-4/pyproject.toml
COPY student-5/pyproject.toml student-5/pyproject.toml
RUN uv sync --locked --no-dev --package student-3-feature --no-install-workspace
COPY shared/contracts/python shared/contracts/python
COPY shared/consumer-protocol/python shared/consumer-protocol/python
RUN uv sync --locked --no-dev --package student-3-feature && uv cache clean

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 10003 propertyscope && useradd --uid 10003 --gid propertyscope --create-home --shell /usr/sbin/nologin propertyscope
COPY --from=builder --chown=propertyscope:propertyscope /app/.venv /app/.venv
COPY --from=builder --chown=propertyscope:propertyscope /app/shared/contracts /app/shared/contracts
COPY --from=builder --chown=propertyscope:propertyscope /app/shared/consumer-protocol /app/shared/consumer-protocol

FROM runtime AS database
ENV PYTHONPATH=/app/student-3/database/src PORT=5302 SUBURB_DB_PATH=/var/lib/propertyscope-suburbs/suburbs.sqlite3
RUN install -d --owner=propertyscope --group=propertyscope /var/lib/propertyscope-suburbs
COPY --chown=propertyscope:propertyscope student-3/database/src student-3/database/src
USER propertyscope
EXPOSE 5302
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=20 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5302/health/ready', timeout=2)"]
CMD ["gunicorn", "--bind=0.0.0.0:5302", "--workers=1", "--threads=4", "propertyscope_suburb_store.app:create_app()"]

FROM runtime AS backend
ENV PYTHONPATH=/app/student-3/backend/src PORT=5301
COPY --chown=propertyscope:propertyscope student-3/backend/src student-3/backend/src
USER propertyscope
EXPOSE 5301
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=20 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5301/health/ready', timeout=2)"]
CMD ["gunicorn", "--bind=0.0.0.0:5301", "--workers=1", "--threads=4", "propertyscope_suburb_analytics.app:create_app()"]

FROM nginxinc/nginx-unprivileged:1.29.1-alpine3.22-slim AS frontend
COPY student-3/frontend /usr/share/nginx/html
COPY shared/frontend/design-system /usr/share/nginx/html/design-system
COPY shared/frontend/browser /usr/share/nginx/html/browser
COPY shared/frontend/ai-chat /usr/share/nginx/html/ai-chat
COPY shared/frontend/mapping /usr/share/nginx/html/mapping
COPY student-3/frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=20 CMD ["wget", "--quiet", "--tries=1", "--spider", "http://127.0.0.1:8080/"]
