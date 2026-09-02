# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.12.13

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 10003 propertyscope && useradd --uid 10003 --gid propertyscope --create-home --shell /usr/sbin/nologin propertyscope

FROM runtime AS database
ENV PYTHONPATH=/app/student-3/database/src PORT=5302 SUBURB_DB_PATH=/var/lib/propertyscope-suburbs/suburbs.sqlite3
RUN install -d --owner=propertyscope --group=propertyscope /var/lib/propertyscope-suburbs
COPY --chown=propertyscope:propertyscope student-3/database/src student-3/database/src
USER propertyscope
EXPOSE 5302
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=20 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5302/health/ready', timeout=2)"]
CMD ["python", "-m", "propertyscope_suburb_store.app"]

FROM runtime AS backend
ENV PYTHONPATH=/app/student-3/backend/src PORT=5301
COPY --chown=propertyscope:propertyscope student-3/backend/src student-3/backend/src
USER propertyscope
EXPOSE 5301
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=20 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5301/health/ready', timeout=2)"]
CMD ["python", "-m", "propertyscope_suburb_analytics.app"]

FROM nginxinc/nginx-unprivileged:1.29.1-alpine3.22-slim AS frontend
COPY student-3/frontend /usr/share/nginx/html
COPY shared/frontend/design-system /usr/share/nginx/html/design-system
COPY shared/frontend/browser /usr/share/nginx/html/browser
COPY shared/frontend/ai-chat /usr/share/nginx/html/ai-chat
COPY shared/frontend/mapping /usr/share/nginx/html/mapping
COPY student-3/frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=20 CMD ["wget", "--quiet", "--tries=1", "--spider", "http://127.0.0.1:8080/"]
