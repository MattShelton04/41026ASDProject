# syntax=docker/dockerfile:1.7
FROM nginxinc/nginx-unprivileged:1.29.1-alpine3.22-slim

COPY shared/frontend /usr/share/nginx/html
COPY shared/frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=20 \
  CMD ["wget", "--quiet", "--tries=1", "--spider", "http://127.0.0.1:8080/healthz"]
