# syntax=docker/dockerfile:1.7

ARG UV_VERSION=0.12.1
ARG PYTHON_VERSION=3.12.13
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=uv /uv /uvx /bin/
WORKDIR /app

# Workspace manifests are required for locked resolution; feature source is excluded.
COPY pyproject.toml uv.lock ./
COPY ai-services/agent-core/pyproject.toml ai-services/agent-core/pyproject.toml
COPY ai-services/ai-mode/pyproject.toml ai-services/ai-mode/pyproject.toml
COPY ai-services/mcp-server/pyproject.toml ai-services/mcp-server/pyproject.toml
COPY ai-services/rag-server/pyproject.toml ai-services/rag-server/pyproject.toml
COPY shared/consumer-protocol/pyproject.toml shared/consumer-protocol/pyproject.toml
COPY shared/contracts/pyproject.toml shared/contracts/pyproject.toml
COPY shared/testkit/pyproject.toml shared/testkit/pyproject.toml
COPY shared/tool-runtime/pyproject.toml shared/tool-runtime/pyproject.toml
COPY student-1/pyproject.toml student-1/pyproject.toml
COPY student-2/pyproject.toml student-2/pyproject.toml
COPY student-3/pyproject.toml student-3/pyproject.toml
COPY student-4/pyproject.toml student-4/pyproject.toml
COPY student-5/pyproject.toml student-5/pyproject.toml
RUN uv sync --locked --no-dev --package ai-mode --package mcp-server --package rag-server --no-install-workspace

COPY ai-services/agent-core/src ai-services/agent-core/src
COPY ai-services/ai-mode/src ai-services/ai-mode/src
COPY ai-services/mcp-server/src ai-services/mcp-server/src
COPY ai-services/rag-server/src ai-services/rag-server/src
COPY shared/contracts/python shared/contracts/python
COPY shared/tool-runtime/src shared/tool-runtime/src
COPY shared/frontend shared/frontend
COPY scripts/__init__.py scripts/__init__.py
COPY scripts/devtools/__init__.py scripts/devtools/__init__.py
COPY scripts/devtools/container_entry.py scripts/devtools/container_entry.py
COPY scripts/devtools/runtime_settings.py scripts/devtools/runtime_settings.py
COPY scripts/devtools/service_auth.py scripts/devtools/service_auth.py
RUN uv sync --locked --no-dev --package ai-mode --package mcp-server --package rag-server && uv cache clean

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 10001 ai-services \
    && useradd --uid 10001 --gid ai-services --create-home --shell /usr/sbin/nologin ai-services \
    && install -d --owner ai-services --group ai-services /var/lib/ai-mode /var/lib/rag
COPY --from=builder --chown=ai-services:ai-services /app/.venv /app/.venv
COPY --from=builder --chown=ai-services:ai-services /app/ai-services /app/ai-services
COPY --from=builder --chown=ai-services:ai-services /app/shared /app/shared
COPY --from=builder --chown=ai-services:ai-services /app/scripts /app/scripts
USER ai-services
EXPOSE 5005 5011 5012
CMD ["python", "-m", "scripts.devtools.container_entry", "ai-mode"]
