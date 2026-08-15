# Ollama local runtime and AI-mode operations

## Assignment path

The course specification requires the integrated services to be containerised and run
through the shared Docker Compose application. Release integration and showcase
evidence should therefore use the Compose-managed Ollama profile. A native Ollama
installation remains a developer convenience for faster local iteration; it is not the
canonical integration topology.

Both paths use the same native Ollama `/api/chat` and `/api/tags` adapter, logical model
profile, prompts, and tests. Routing is configuration only—feature code never knows an
Ollama hostname or model tag.

## Prerequisites

1. Install `uv` and reproduce the locked workspace as described in the root README.
2. Install [Docker Desktop](https://docs.docker.com/desktop/) on Windows or macOS, or a
   current Docker Engine with the Compose plugin on Linux.
3. On Docker Desktop, use Linux containers and allow at least 6 GB of memory for the
   first local model profile. Start Docker Desktop before running the commands below.
4. Confirm both the client and daemon are available:

```text
docker info
docker compose version
```

The first container start downloads the pinned Ollama runtime image and
`qwen2.5:3b`. The model and AI-mode SQLite state use named volumes and survive a
normal `down`/`up` cycle.

### Automatic NVIDIA GPU acceleration

The portable base Compose topology is deliberately CPU-compatible. The canonical
`uv run scripts/dev.py up` helper detects whether Docker advertises the NVIDIA runtime
and merges `docker-compose.gpu.yml` automatically when it does. Use `--cpu-only` for an
intentional CPU run, or `--gpu` when acceleration is required and startup should fail
fast if it is unavailable. On Windows, NVIDIA acceleration requires
[Docker Desktop's WSL 2 GPU path](https://docs.docker.com/desktop/features/gpu/), a
supported NVIDIA GPU, current Windows/NVIDIA drivers, and a current WSL kernel. The
override follows Docker's
[Compose GPU reservation model](https://docs.docker.com/compose/how-tos/gpu-support/)
and Ollama's [container GPU guidance](https://docs.ollama.com/docker). Confirm Docker
advertises the `nvidia` runtime before opting in:

```text
nvidia-smi
docker info
```

For lower-level Compose operation, merge the hardware override explicitly:

```text
docker compose --file docker-compose.yml --file docker-compose.gpu.yml --profile ollama-container up --detach --wait --wait-timeout 120 ollama
docker compose --file docker-compose.yml --file docker-compose.gpu.yml --profile ollama-container run --rm ollama-init
docker compose --file docker-compose.yml --file docker-compose.gpu.yml --profile release-0 up --detach --build --wait --wait-timeout 120 ai-mode
```

The override requests NVIDIA device `0` by default. On a multi-GPU host, set
`OLLAMA_GPU_DEVICE_ID` in the uncommitted root `.env` file to the desired Docker-visible
device ID. The override intentionally uses one explicit device rather than claiming
every GPU on a shared development machine.

Verify device visibility and actual model placement after a generation:

```text
docker compose --file docker-compose.yml --file docker-compose.gpu.yml exec ollama nvidia-smi
curl http://localhost:11434/api/ps
```

In `/api/ps`, a positive `size_vram` confirms model data is resident on GPU. CI
validates the merged GPU configuration but does not run it because hosted runners do
not promise an NVIDIA device.

## Recommended: fully containerised runtime

Docker Compose is the single lifecycle and routing source of truth. The same commands
work in PowerShell, Bash, CI, and agent-run terminals:

```text
docker compose --profile release-0 --profile ollama-container config --quiet
docker compose --profile ollama-container up --detach --wait --wait-timeout 120 ollama
docker compose --profile ollama-container run --rm ollama-init
docker compose --profile release-0 up --detach --build --wait --wait-timeout 120 ai-mode
```

This starts pinned Ollama, runs the model initializer to successful completion, builds
the non-root AI-mode image, and waits until AI-mode reports both store and model
readiness. Keeping the completed one-shot job out of `up --wait` avoids treating its
normal exit as an unhealthy long-running service. Compose enables strict readiness with
`AI_MODE_REQUIRE_OLLAMA_READY=true`; host development defaults it to `false` so CRUD and
run inspection remain available with a truthful degraded status when Ollama is offline.

After startup, run the installed provider diagnostic:

```text
uv run ai-mode-ollama-smoke
```

It performs one real JSON-Schema-constrained generation through the production adapter.
It owns neither Docker lifecycle nor application/business behavior, and it reuses the
service's settings parser, logical model profile, and provider factory.

Ordinary Compose commands remain the operational interface:

```text
docker compose ps
docker compose logs --follow ai-mode ollama
docker compose down --remove-orphans
```

`down` preserves downloaded models and run state. Adding `--volumes` permanently removes
both named volumes and should be used only when a clean runtime is intended.

Host inspection endpoints are bound to loopback during development:

| Endpoint | Purpose |
|---|---|
| `http://localhost:5005/health/live` | AI-mode process liveness |
| `http://localhost:5005/health/ready` | SQLite plus configured-model readiness |
| `http://localhost:5005/api/v1/model-profiles` | Supported tags and runtime context/output budgets |
| `http://localhost:11434/api/tags` | Ollama's installed model inventory |

Future shared-edge integration should use the internal `ai-mode:5005` service address
and may remove the host AI-mode port from the release-evidence topology.

## Local development loop

Use the deterministic quality gate for normal code changes; it requires neither Docker
nor a model download:

```text
uv sync --locked --all-packages --all-groups
uv run python scripts/check.py
```

For fast application iteration with the production provider boundary, run only Ollama
in Compose and AI-mode from the host:

```text
docker compose --profile ollama-container up --detach --wait ollama
docker compose --profile ollama-container run --rm ollama-init
uv run flask --app ai_mode:create_app run --port 5005
uv run ai-mode-ollama-smoke
```

This hybrid loop uses the host default `OLLAMA_BASE_URL=http://localhost:11434`, so no
routing override is needed. Use the fully containerised command for integration and
release evidence. The AI-mode image has no source bind mount by design; after changing
service code, rerun its `up --build` command to exercise the deployable artifact.

The diagnostic is a real provider call, not a complete feature task. Full agent-loop
tests use deterministic fake providers and tools. The non-product integration fixture
provides an explicit live end-to-end demonstration; production claims still require an
approved student feature and its allowlisted HTTP tools. With no tool catalogue selected,
the empty tool registry correctly rejects invented calls.

## Native Ollama developer path

Install Ollama using its [official platform instructions](https://docs.ollama.com/) and
prepare the same model:

```text
ollama pull qwen2.5:3b
ollama serve
```

Run AI-mode directly on the host:

```text
uv run flask --app ai_mode:create_app run --port 5005
```

The default `OLLAMA_BASE_URL=http://localhost:11434` is correct for that path. To run
only AI-mode in Docker while Ollama remains native, merge the explicit developer
override and leave the `ollama-container` profile disabled:

```text
docker compose --file docker-compose.yml --file docker-compose.native-ollama.yml --profile release-0 up --detach --build --wait --wait-timeout 120 ai-mode
```

AI-mode then routes to `http://host.docker.internal:11434`. Docker Desktop provides
that hostname; the base Compose file supplies Docker's `host-gateway` mapping for Linux.
Override `AI_MODE_OLLAMA_BASE_URL` only for an intentional nonstandard host endpoint.

## Routing and configuration

| Caller | Runtime | Configured base URL |
|---|---|---|
| Host Python AI-mode | Native Ollama | `http://localhost:11434` |
| Container AI-mode | Native Ollama override | `http://host.docker.internal:11434` |
| Container AI-mode | Compose Ollama | `http://ollama:11434` |

The committed Compose files own container routing, so users do not need shell-specific
environment syntax. Supported tuning variables are listed in
`shared/configuration/.env.example`; put local overrides in an uncommitted root `.env`
file. Image and dependency versions stay reviewed and pinned in source.

`AI_MODE_DEFAULT_MODEL_PROFILE` selects the registry profile required by readiness and
used when a run omits `model_profile`. Compose's `OLLAMA_MODEL` controls only the
one-shot pull container and must be the corresponding concrete tag. The bundled choices
are `local-standard.v1` / `qwen2.5:3b`, constrained `local-small.v1` /
`qwen2.5:1.5b`, smoke-only `local-smoke.v1` / `qwen2.5:0.5b`,
`local-balanced.v1` / `llama3.1:8b`, and `local-reasoning.v1` /
`deepseek-r1:8b`. Optional models can be prepared with, for
example:

```text
docker compose --profile ollama-container exec ollama ollama pull llama3.1:8b
uv run ai-mode-ollama-smoke --profile local-balanced.v1
```

Set both the profile and pull tag in the uncommitted `.env` before starting Compose if
an optional profile should become the default.

## Autonomous inspection and troubleshooting

Compose returns nonzero on invalid configuration, build/start failures, or readiness
timeouts. `ai-mode-ollama-smoke` returns nonzero on unhealthy/missing models, provider
errors, invalid schema output, or unexpected diagnostic content. These standard
interfaces support developers, CI, and coding agents without UI automation or a custom
Docker wrapper.

If startup fails:

1. run `docker compose ps`;
2. inspect `docker compose logs ai-mode ollama ollama-init`;
3. confirm Docker Desktop has sufficient memory and disk;
4. confirm no other process owns ports 5005 or 11434; and
5. rerun `up`—image and model downloads reuse Docker cache and named-volume data.

Deterministic unit tests never require Ollama or Docker. The real-model diagnostic is a
separate operational/evaluation check because downloads are large, generation is
hardware-dependent, and probabilistic runtime availability should not weaken the core
quality gate.
