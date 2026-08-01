# syntax=docker/dockerfile:1.7

ARG UV_VERSION=0.12.1
ARG PYTHON_VERSION=3.12.13

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

# Copy workspace metadata first so third-party dependencies remain cacheable when
# production source changes. All member manifests are needed for uv workspace discovery.
COPY pyproject.toml uv.lock ./
COPY ai-services/agent-core/pyproject.toml ai-services/agent-core/pyproject.toml
COPY ai-services/ai-mode/pyproject.toml ai-services/ai-mode/pyproject.toml
COPY shared/contracts/pyproject.toml shared/contracts/pyproject.toml
COPY shared/testkit/pyproject.toml shared/testkit/pyproject.toml
COPY student-1/pyproject.toml student-1/pyproject.toml
COPY student-2/pyproject.toml student-2/pyproject.toml
COPY student-3/pyproject.toml student-3/pyproject.toml
COPY student-4/pyproject.toml student-4/pyproject.toml
COPY student-5/pyproject.toml student-5/pyproject.toml

RUN uv sync --locked --no-dev --package ai-mode --no-install-workspace

COPY ai-services/agent-core/src ai-services/agent-core/src
COPY ai-services/ai-mode/src ai-services/ai-mode/src
COPY shared/contracts/python shared/contracts/python

RUN uv sync --locked --no-dev --package ai-mode \
    && uv cache clean

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --gid 10001 ai-mode \
    && useradd --uid 10001 --gid ai-mode --create-home --shell /usr/sbin/nologin ai-mode \
    && install -d --owner ai-mode --group ai-mode /var/lib/ai-mode

COPY --from=builder --chown=ai-mode:ai-mode /app/.venv /app/.venv
COPY --from=builder --chown=ai-mode:ai-mode /app/ai-services /app/ai-services
COPY --from=builder --chown=ai-mode:ai-mode /app/shared/contracts /app/shared/contracts

USER ai-mode

EXPOSE 5005

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=60 \
    CMD ["python", "-c", "import json, sys, urllib.request; response = json.load(urllib.request.urlopen('http://127.0.0.1:5005/health/ready', timeout=2)); sys.exit(0 if response.get('status') == 'healthy' else 1)"]

CMD ["gunicorn", "--bind=0.0.0.0:5005", "--workers=1", "--threads=4", "--timeout=180", "--graceful-timeout=30", "--access-logfile=-", "--error-logfile=-", "ai_mode:create_app()"]
