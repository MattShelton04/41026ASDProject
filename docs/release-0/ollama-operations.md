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
`qwen2.5:0.5b`. The model and AI-mode SQLite state use named volumes and survive a
normal `down`/`up` cycle.

## Recommended: fully containerised runtime

Docker Compose is the single lifecycle and routing source of truth. The same commands
work in PowerShell, Bash, CI, and agent-run terminals:

```text
docker compose --profile release-0 --profile ollama-container config --quiet
docker compose --profile release-0 --profile ollama-container up --detach --build --wait --wait-timeout 600
```

This builds the non-root AI-mode image, starts pinned Ollama, pulls the configured model
through a one-shot initializer, and waits until AI-mode reports both store and model
readiness. Compose enables strict provider readiness with
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
| `http://localhost:11434/api/tags` | Ollama's installed model inventory |

Future shared-edge integration should use the internal `ai-mode:5005` service address
and may remove the host AI-mode port from the release-evidence topology.

## Native Ollama developer path

Install Ollama using its [official platform instructions](https://docs.ollama.com/) and
prepare the same model:

```text
ollama pull qwen2.5:0.5b
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
