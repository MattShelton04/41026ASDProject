# Shared configuration

Keep non-secret configuration templates here. Copy `.env.example` to a local
untracked environment file; never commit credentials or cloud secrets.

`ai-mode` uses Ollama's native API for structured output and timing metadata. It also
accepts the course guide's `/v1` URL and normalizes that suffix. Release-gated service
flags remain false until their applicable local release and must remain false in the
Release 2 cloud deployment.

Feature HTTP tools are disabled unless `AI_MODE_TOOL_CATALOG_PATH` names a validated
startup catalogue. Do not place credentials in that file and do not expose arbitrary
caller/model URLs. `AI_MODE_EVIDENCE_ACCESS_TOKEN` is a local secret; leaving it unset
removes the development evidence route entirely.
