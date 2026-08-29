# Shared runtime assets

This directory is the development-overlay mountpoint for locally vendored Shared browser assets.
`docker-compose.dev.yml` mounts `shared/frontend/vendor/` here read-only; the production Feature 1
image copies that same source directory. Do not duplicate vendor files in this feature slice.
