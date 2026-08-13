# Shared configuration

Keep non-secret configuration templates here. Copy `.env.example` to a local
untracked environment file; never commit credentials or cloud secrets.

`ai-mode` uses Ollama's native API for structured output and timing metadata. It also
accepts the course guide's `/v1` URL and normalizes that suffix. Release-gated service
flags remain false until their applicable local release and must remain false in the
Release 2 cloud deployment.

Feature HTTP tools are disabled unless `AI_MODE_TOOL_CATALOG_PATH` names one validated
catalogue or `AI_MODE_TOOL_CATALOG_PATHS` names an ordered comma-separated set of catalogues.
The settings are mutually exclusive, and duplicate services/tools fail startup. Each file is
a strict startup catalogue. Do not place credentials in those files or expose arbitrary
caller/model URLs. `AI_MODE_EVIDENCE_ACCESS_TOKEN` is a local secret; leaving it unset
removes the development evidence route entirely.

AI-mode selects concrete Ollama tags through its bundled validated model registry.
`AI_MODE_DEFAULT_MODEL_PROFILE` chooses the readiness/default profile and
`AI_MODE_MODEL_REGISTRY_PATH` can name a complete replacement file. In Compose,
`OLLAMA_MODEL` is consumed by the one-shot model puller, so it must correspond to the
selected logical profile. Unknown profiles and non-approved model families fail fast.
