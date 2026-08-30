# Shared browser mountpoint

The development Compose overlay mounts `shared/frontend/browser/` over this directory. Keeping the
mountpoint in the feature source lets Docker Desktop attach that child read-only mount beneath the
read-only Feature 1 frontend mount. The production Dockerfile copies the same shared package here.

Do not duplicate shared browser primitives in this directory.

The feature's HTML entry script owns its deployment cache revision; internal ES module imports are
query-free. Feature-owned JSON requests compose route, refresh and timeout abort signals in
`core/request.js`. The copy is deliberately feature-local because local Node tests execute directly
from the repository while the deployed browser package above is supplied by the separate Shared
image/mount boundary.
