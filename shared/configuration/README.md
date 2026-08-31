# Shared configuration

Keep non-secret service configuration templates here. For the complete development stack, copy the
repository-root `.env.example` to the Git-ignored root `.env`; stack commands load it automatically.
Never commit credentials or cloud secrets.

`ai-mode` uses the OpenAI Responses API for JSON-Schema-guided output, reasoning controls,
and token usage metadata. `OPENAI_API_KEY` is a secret: inject it through the host process
environment or use `OPENAI_API_KEY_FILE` for a mounted secret, and never commit it. Compose
sources its service-scoped secret from the launching shell and mounts it only into AI-mode.
Release-gated service
flags remain false until their applicable local release and must remain false in the
Release 2 cloud deployment.

Feature HTTP tools are disabled unless `AI_MODE_TOOL_CATALOG_PATH` names one validated
catalogue or `AI_MODE_TOOL_CATALOG_PATHS` names an ordered comma-separated set of catalogues.
The settings are mutually exclusive, and duplicate services/tools fail startup. Each file is
a strict startup catalogue. Do not place credentials in those files or expose arbitrary
caller/model URLs. `AI_MODE_EVIDENCE_ACCESS_TOKEN` is a local secret; leaving it unset
removes the development evidence route entirely.

AI-mode selects concrete provider model IDs through its bundled validated model registry.
`AI_MODE_DEFAULT_MODEL_PROFILE` chooses the readiness/default profile and
`AI_MODE_MODEL_REGISTRY_PATH` can name a complete replacement file. Unknown profiles,
providers, and model IDs fail startup validation or a typed provider request.
