# Shared AI chat development mount

This directory is an intentionally empty mount point for `docker-compose.dev.yml`.

The development stack bind-mounts `shared/frontend/ai-chat/` here after mounting the complete
Feature 1 frontend read-only. Production images copy the shared package directly. Do not add a
Feature 1 copy of the shared chat implementation to this directory.
