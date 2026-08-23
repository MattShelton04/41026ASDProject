# Shared browser mountpoint

The development Compose overlay mounts `shared/frontend/browser/` over this directory. Keeping the
mountpoint in the feature source lets Docker Desktop attach that child read-only mount beneath the
read-only Feature 1 frontend mount. The production Dockerfile copies the same shared package here.

Do not duplicate shared browser primitives in this directory.
