# Shared mapping mountpoint

The development Compose overlay mounts `shared/frontend/mapping/` over this directory. Keeping the
mountpoint in the feature source lets Docker Desktop attach that child read-only mount beneath the
read-only feature frontend mount. The production Dockerfile copies the same shared package here.

Do not duplicate provider code in this directory.
