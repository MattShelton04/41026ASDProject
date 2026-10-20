# Multi-agent panel mount point

This directory is intentionally almost empty. The shared multi-agent panel is mounted here at
runtime, so `../multi-agent/index.js` resolves the same way in three places:

- the built image, through `COPY shared/frontend/multi-agent` in `student-2/Dockerfile`;
- the development stack, through the read-only bind mount on `f2-frontend` in
  `docker-compose.dev.yml`;
- Node tests, through `scripts/frontend-test-bootstrap.mjs`.

The package itself lives in `shared/frontend/multi-agent/`. Import only its `index.js` barrel;
`scripts/validate_architecture.py` enforces that.
