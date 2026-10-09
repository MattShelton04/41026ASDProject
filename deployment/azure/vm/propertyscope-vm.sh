#!/usr/bin/env bash
# PropertyScope VM operations (ADR-048). Runs ON the Azure VM as root, delivered by
# `deployment/azure/deploy.sh` through `az vm run-command invoke`; there is no SSH.
#
#   propertyscope-vm.sh deploy          render secrets, pull SHA images, compose up --wait, verify
#   propertyscope-vm.sh ai-on|ai-off    toggle the systemd AI tier and the Compose AI overlay
#   propertyscope-vm.sh status          containers, AI units, listening sockets, certificate
#   propertyscope-vm.sh logs [service]  recent Compose (or AI unit) logs
#   propertyscope-vm.sh validate-data   on-host part of the data-security validation (R2-B6)
#
# Inputs are environment variables exported by the run-command payload (deploy.sh writes them):
#   ACR_LOGIN_SERVER IMAGE_TAG KEY_VAULT_NAME PROPERTYSCOPE_PUBLIC_HOST PROPERTYSCOPE_ACME_EMAIL
#   optional: PROPERTYSCOPE_CLOUD_AI (true|false, default: keep the VM's current state)
#             PROPERTYSCOPE_GIT_SHA PROPERTYSCOPE_REPO_URL PROPERTYSCOPE_EDGE_USER CADDY_IMAGE_TAG
#             PROPERTYSCOPE_FORCE_RECREATE PROPERTYSCOPE_LOG_SERVICE PROPERTYSCOPE_LOG_LINES
#
# Secrets never pass through the run-command payload: the VM's managed identity reads them from
# Key Vault (IMDS token -> Key Vault REST) into root-only files. Nothing here enables `set -x`.
set -euo pipefail
umask 077

readonly ROOT_DIR=/opt/propertyscope
readonly APP_DIR=$ROOT_DIR/app
readonly SECRETS_DIR=$ROOT_DIR/secrets
readonly STATE_DIR=$ROOT_DIR/state
readonly SRC_DIR=$ROOT_DIR/src
readonly AI_USER=propertyscope-ai
readonly AI_HOME=/var/lib/propertyscope-ai
readonly COMPOSE_PROJECT=ps-azure
readonly AI_UNITS=(propertyscope-ai-mode propertyscope-mcp propertyscope-rag propertyscope-multi-agent)
readonly IMDS=http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() {
    printf '[%s] ERROR: %s\n' "$(date -u +%H:%M:%S)" "$*" >&2
    exit 1
}
require_env() {
    local name
    for name in "$@"; do
        [[ -n ${!name:-} ]] || die "$name is required"
    done
}

wait_for_bootstrap() {
    if command -v cloud-init >/dev/null 2>&1; then
        cloud-init status --wait >/dev/null 2>&1 || true
    fi
    [[ -f /etc/propertyscope/bootstrap-complete ]] || die "cloud-init bootstrap has not completed"
    local tool
    for tool in docker jq curl git; do
        command -v "$tool" >/dev/null 2>&1 || die "$tool is missing; inspect /var/log/cloud-init-output.log"
    done
    docker compose version >/dev/null || die "the Docker Compose plugin is missing"
    install -d -m 0700 "$SECRETS_DIR" "$STATE_DIR"
}

cloud_ai_state() {
    local requested=${PROPERTYSCOPE_CLOUD_AI:-}
    if [[ -z $requested && -f $STATE_DIR/cloud-ai ]]; then
        requested=$(<"$STATE_DIR/cloud-ai")
    fi
    case ${requested:-false} in
        true) echo true ;;
        false) echo false ;;
        *) die "PROPERTYSCOPE_CLOUD_AI must be true or false" ;;
    esac
}

compose() {
    local files=(-f docker-compose.yml -f deployment/enabled-features.compose.yml -f docker-compose.azure.yml)
    if [[ $(cloud_ai_state) == true ]]; then
        files+=(-f docker-compose.azure-ai.yml)
    fi
    (cd "$APP_DIR" && docker compose --project-name "$COMPOSE_PROJECT" "${files[@]}" --profile release-0 "$@")
}

# --- Managed identity ------------------------------------------------------------------------

imds_token() {
    curl -fsS --retry 5 --retry-delay 2 -H Metadata:true "$IMDS&resource=$1" | jq -er .access_token
}

# Prints a Key Vault secret value; returns 3 for a missing optional secret.
kv_get() {
    local name=$1 optional=${2:-} response status
    response=$(curl -sS --retry 3 -w '\n%{http_code}' -H "Authorization: Bearer $KV_TOKEN" \
        "https://${KEY_VAULT_NAME}.vault.azure.net/secrets/${name}?api-version=7.4")
    status=${response##*$'\n'}
    if [[ $status == 200 ]]; then
        jq -er .value <<<"${response%$'\n'*}"
        return 0
    fi
    if [[ $status == 404 && $optional == optional ]]; then
        return 3
    fi
    die "Key Vault secret '$name' could not be read (HTTP $status). Run 'deploy.sh secrets' first."
}

write_secret() {
    local name=$1 value=$2 mode=${3:-0444} temporary
    [[ -n $value ]] || die "refusing to write empty secret $name"
    temporary=$(mktemp "$SECRETS_DIR/.${name}.XXXXXX")
    printf '%s' "$value" >"$temporary"
    chmod "$mode" "$temporary"
    mv -f "$temporary" "$SECRETS_DIR/$name"
}

acr_login() {
    require_env ACR_LOGIN_SERVER
    local arm refresh
    arm=$(imds_token https://management.azure.com/)
    refresh=$(curl -fsS --retry 3 -X POST "https://${ACR_LOGIN_SERVER}/oauth2/exchange" \
        --data-urlencode grant_type=access_token \
        --data-urlencode "service=${ACR_LOGIN_SERVER}" \
        --data-urlencode "access_token=${arm}" | jq -er .refresh_token)
    printf '%s' "$refresh" |
        docker login "$ACR_LOGIN_SERVER" --username 00000000-0000-0000-0000-000000000000 --password-stdin >/dev/null
    log "ACR login with the VM managed identity (AcrPull)"
}

acr_logout() {
    docker logout "$ACR_LOGIN_SERVER" >/dev/null 2>&1 || true
}

render_application_secrets() {
    require_env KEY_VAULT_NAME
    KV_TOKEN=$(imds_token https://vault.azure.net)
    local internal runner f1_password f4_password edge_password edge_hash caddy_image
    internal=$(kv_get internal-token)
    runner=$(kv_get runner-token)
    f1_password=$(kv_get f1-postgres-password)
    f4_password=$(kv_get f4-postgres-password)
    edge_password=$(kv_get edge-basic-auth-password)
    write_secret internal-token "$internal"
    write_secret runner-token "$runner"
    write_secret f1-postgres-password "$f1_password"
    write_secret f4-postgres-password "$f4_password"
    write_secret f1-database-url "postgresql://${PROPERTYSCOPE_POSTGRES_USER:-propertyscope}:$(jq -rn --arg v "$f1_password" '$v|@uri')@f1-postgres:5432/${PROPERTYSCOPE_POSTGRES_DB:-propertyscope}"
    write_secret f4-database-url "postgresql://${PROPERTYSCOPE_DUE_DILIGENCE_USER:-due_diligence}:$(jq -rn --arg v "$f4_password" '$v|@uri')@f4-postgres:5432/${PROPERTYSCOPE_DUE_DILIGENCE_DB:-due_diligence}"
    caddy_image="${ACR_LOGIN_SERVER}/propertyscope/mirror/caddy:${CADDY_IMAGE_TAG:-2.10.2-alpine}"
    edge_hash=$(printf '%s\n' "$edge_password" |
        docker run --rm -i --network none --entrypoint caddy "$caddy_image" hash-password | tail -n 1)
    [[ $edge_hash == \$2* ]] || die "could not hash the edge operator password"
    write_secret edge-basic-auth "${PROPERTYSCOPE_EDGE_USER:-propertyscope-operator} ${edge_hash}"
    log "Rendered application secrets from Key Vault ${KEY_VAULT_NAME} (values not logged)"
}

render_ai_secrets() {
    KV_TOKEN=${KV_TOKEN:-$(imds_token https://vault.azure.net)}
    local name value
    # The AI-mode entry token is a Compose secret for the edge and the backends (non-root container
    # users), so it is world-readable inside the root-only directory. The others stay root-only:
    # only systemd (as root) reads them into the host AI environment file.
    value=$(kv_get ai-mode-service-token)
    write_secret ai-mode-service-token "$value" 0444
    for name in mcp-service-token rag-service-token multi-agent-service-token; do
        value=$(kv_get "$name")
        write_secret "$name" "$value" 0400
    done
    if value=$(kv_get openai-api-key optional); then
        write_secret openai-api-key "$value" 0400
    else
        # systemd LoadCredential needs the file; AI-mode then reports its provider as not ready.
        log "WARNING: Key Vault has no openai-api-key; AI-mode will report its provider as not ready"
        write_secret openai-api-key "offline-no-provider-key-configured" 0400
    fi
}

remove_ai_secrets() {
    rm -f "$SECRETS_DIR"/{ai-mode-service-token,mcp-service-token,rag-service-token} \
        "$SECRETS_DIR"/{multi-agent-service-token,openai-api-key,host-ai.env}
}

# --- Application -----------------------------------------------------------------------------

write_compose_environment() {
    require_env ACR_LOGIN_SERVER IMAGE_TAG PROPERTYSCOPE_PUBLIC_HOST PROPERTYSCOPE_ACME_EMAIL
    local digest
    digest=$(cd "$APP_DIR/deployment/azure" &&
        find Caddyfile caddy nginx compose -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16)
    umask 022
    cat >"$APP_DIR/.env" <<EOF
# Written by propertyscope-vm.sh; non-secret values only.
COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT}
ACR_LOGIN_SERVER=${ACR_LOGIN_SERVER}
IMAGE_TAG=${IMAGE_TAG}
CADDY_IMAGE_TAG=${CADDY_IMAGE_TAG:-2.10.2-alpine}
PROPERTYSCOPE_PUBLIC_HOST=${PROPERTYSCOPE_PUBLIC_HOST}
PROPERTYSCOPE_ACME_EMAIL=${PROPERTYSCOPE_ACME_EMAIL}
PROPERTYSCOPE_SECRETS_DIR=${SECRETS_DIR}
PROPERTYSCOPE_EDGE_CONFIG_SHA=${digest}
EOF
    umask 077
}

verify_deployment() {
    local releases accepted attempt
    releases=$(compose exec -T shared-frontend wget -qO- \
        'http://127.0.0.1:8080/api/data-platform/v1/dataset-releases?status=accepted&limit=100' || echo '{}')
    accepted=$(jq '[.items[]? | select(.status == "accepted")] | length' <<<"$releases" 2>/dev/null || echo 0)
    if [[ $accepted -gt 0 ]]; then
        log "Feature 1 data: ${accepted} accepted releases (seeded demonstration baseline unless real releases were published)"
    else
        log "WARNING: Feature 1 reports no accepted releases; inspect 'deploy.sh logs f1-db-api'"
    fi
    for attempt in $(seq 1 24); do
        if curl -fsS -o /dev/null --max-time 5 --resolve "${PROPERTYSCOPE_PUBLIC_HOST}:443:127.0.0.1" \
            "https://${PROPERTYSCOPE_PUBLIC_HOST}/healthz"; then
            log "HTTPS edge is serving a trusted certificate for ${PROPERTYSCOPE_PUBLIC_HOST}"
            return 0
        fi
        sleep 5
    done
    log "WARNING: HTTPS is not trusted yet (first certificate issuance can take a few minutes)"
}

# The demonstration baseline (about 10 synthetic records per accepted dataset) is seeded by the
# Feature 1 database migrations that f1-db-api applies on start (PROPERTYSCOPE_AUTO_MIGRATE).
# Once per VM this also runs the registered `fixture-property` collection - the same job as
# `dev.py data collect fixture-property` - so the runner -> release builder -> loader pipeline is
# proven in the cloud. It needs no network, ends at a candidate awaiting human review and is
# never published automatically.
seed_fixture_candidate() {
    if [[ ${PROPERTYSCOPE_SEED_FIXTURE:-true} != true || -f $STATE_DIR/fixture-collected ]]; then
        return 0
    fi
    log "Running the fixture-property collection once (candidate release, human review required)"
    if compose exec -T f1-backend python - <<'PY'; then
import json, time, urllib.request, uuid

BASE = "http://127.0.0.1:5201/api/data-platform/v1/"


def call(method, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


jobs = call("GET", "jobs?limit=100")["items"]
job = next(item for item in jobs if item.get("profile_key") == "fixture-property-full")
scope = {"profile": "full-data", "all_records": True}
body = {"run_mode": "full_refresh", "scope": scope}
call("POST", f"jobs/{job['id']}/plans", body)
operation = str(uuid.uuid4())
run = call(
    "POST",
    f"jobs/{job['id']}/runs",
    body,
    {"Idempotency-Key": f"azure-seed-{operation}", "X-Request-ID": operation},
)["run"]
deadline = time.monotonic() + 240
while time.monotonic() < deadline:
    status = call("GET", f"ingestion-runs/{run['id']}")["run"]["status"]
    if status in {"succeeded", "failed", "cancelled"}:
        break
    time.sleep(2)
print(f"fixture-property run {run['id']}: {status}")
raise SystemExit(0 if status == "succeeded" else 1)
PY
        touch "$STATE_DIR/fixture-collected"
    else
        log "WARNING: the fixture-property collection did not succeed; inspect 'deploy.sh logs f1-runner'"
    fi
}

deploy() {
    wait_for_bootstrap
    require_env ACR_LOGIN_SERVER IMAGE_TAG KEY_VAULT_NAME PROPERTYSCOPE_PUBLIC_HOST PROPERTYSCOPE_ACME_EMAIL
    local cloud_ai
    cloud_ai=$(cloud_ai_state)
    write_compose_environment
    acr_login
    trap acr_logout EXIT
    log "Pulling ${IMAGE_TAG} images"
    compose pull --quiet
    render_application_secrets
    acr_logout
    trap - EXIT
    local up_arguments=(up --detach --wait --wait-timeout 300 --no-build --remove-orphans)
    if [[ ${PROPERTYSCOPE_FORCE_RECREATE:-false} == true ]]; then
        up_arguments+=(--force-recreate)
    fi
    if [[ $cloud_ai == true ]]; then
        start_ai_tier
    else
        stop_ai_tier
    fi
    log "Starting the stack (cloud AI: ${cloud_ai})"
    compose "${up_arguments[@]}"
    printf '%s\n' "$cloud_ai" >"$STATE_DIR/cloud-ai"
    printf '%s\n' "$IMAGE_TAG" >"$STATE_DIR/image-tag"
    verify_deployment
    seed_fixture_candidate
    docker image prune --force >/dev/null || true
    summary deploy
}

# --- Cloud AI tier (bonus R2-B1..B4) ------------------------------------------------------------

as_ai_user() {
    setpriv --reuid="$AI_USER" --regid="$AI_USER" --init-groups --inh-caps=-all \
        env HOME="$AI_HOME" UV_CACHE_DIR="$AI_HOME/uv-cache" PATH=/usr/local/bin:/usr/bin:/bin "$@"
}

checkout_source() {
    # The host AI tier runs the same commit as the deployed images.
    if [[ -z ${PROPERTYSCOPE_GIT_SHA:-} && -f $STATE_DIR/image-tag ]]; then
        PROPERTYSCOPE_GIT_SHA=$(<"$STATE_DIR/image-tag")
        PROPERTYSCOPE_GIT_SHA=${PROPERTYSCOPE_GIT_SHA%-dirty}
    fi
    require_env PROPERTYSCOPE_GIT_SHA PROPERTYSCOPE_REPO_URL
    [[ $PROPERTYSCOPE_GIT_SHA =~ ^[0-9a-f]{40}$ ]] || die "PROPERTYSCOPE_GIT_SHA must be a full commit SHA"
    install -d -m 0750 -o "$AI_USER" -g "$AI_USER" "$SRC_DIR" "$AI_HOME"
    local token=""
    if token=$(kv_get github-repo-token optional); then
        # Private repository: pass the read-only token through git's environment configuration,
        # never on the command line.
        export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.extraHeader
        GIT_CONFIG_VALUE_0="Authorization: Basic $(printf 'x-access-token:%s' "$token" | base64 -w0)"
        export GIT_CONFIG_VALUE_0
    fi
    if [[ ! -d $SRC_DIR/.git ]]; then
        as_ai_user git -C "$SRC_DIR" init --quiet
        as_ai_user git -C "$SRC_DIR" remote add origin "$PROPERTYSCOPE_REPO_URL"
    fi
    as_ai_user git -C "$SRC_DIR" fetch --quiet --depth 1 origin "$PROPERTYSCOPE_GIT_SHA"
    as_ai_user git -C "$SRC_DIR" checkout --quiet --force FETCH_HEAD
    unset GIT_CONFIG_COUNT GIT_CONFIG_KEY_0 GIT_CONFIG_VALUE_0
    (cd "$SRC_DIR" && as_ai_user uv sync --quiet --locked --all-packages --all-groups)
    log "Host AI source at ${PROPERTYSCOPE_GIT_SHA} with the locked workspace"
}

write_host_ai_environment() {
    local token
    (
        set +u
        AI_MODE_SERVICE_TOKEN=$(<"$SECRETS_DIR/ai-mode-service-token")
        MCP_SERVICE_TOKEN=$(<"$SECRETS_DIR/mcp-service-token")
        RAG_SERVICE_TOKEN=$(<"$SECRETS_DIR/rag-service-token")
        MULTI_AGENT_SERVICE_TOKEN=$(<"$SECRETS_DIR/multi-agent-service-token")
        export AI_MODE_SERVICE_TOKEN MCP_SERVICE_TOKEN RAG_SERVICE_TOKEN MULTI_AGENT_SERVICE_TOKEN
        cd "$SRC_DIR"
        as_ai_user .venv/bin/python -m scripts.devtools.cloud host-env --mode "${PROPERTYSCOPE_AI_MODE:-combined}"
    ) >"$SECRETS_DIR/host-ai.env.tmp"
    chmod 0600 "$SECRETS_DIR/host-ai.env.tmp"
    mv -f "$SECRETS_DIR/host-ai.env.tmp" "$SECRETS_DIR/host-ai.env"
    token=$(grep -c '=' "$SECRETS_DIR/host-ai.env")
    log "Host AI environment prepared (${token} settings, credentials not logged)"
}

with_host_ai_environment() {
    (
        set -a
        # shellcheck disable=SC1091
        . "$SECRETS_DIR/host-ai.env"
        set +a
        cd "$SRC_DIR"
        as_ai_user "$@"
    )
}

start_ai_tier() {
    require_env KEY_VAULT_NAME
    render_ai_secrets
    checkout_source
    write_host_ai_environment
    install -m 0644 "$APP_DIR"/deployment/azure/systemd/*.service "$APP_DIR"/deployment/azure/systemd/*.target \
        /etc/systemd/system/
    systemctl daemon-reload
    log "Preparing the RAG embedding model (downloads once into the AI user's runtime store)"
    with_host_ai_environment .venv/bin/rag-server prepare-model >/dev/null
    systemctl enable --now propertyscope-ai.target >/dev/null
    systemctl restart "${AI_UNITS[@]}" 2>/dev/null || true
    wait_for_ai_tier
    local corpus
    while IFS= read -r corpus; do
        [[ -n $corpus ]] || continue
        with_host_ai_environment .venv/bin/rag-server ingest "$corpus" >/dev/null &&
            log "Ingested RAG corpus ${corpus}" || log "WARNING: could not ingest ${corpus}"
    done < <(jq -r '.features[].ai.rag_corpus // empty' "$SRC_DIR/deployment/enabled-features.v1.json")
    printf 'true\n' >"$STATE_DIR/cloud-ai"
}

wait_for_ai_tier() {
    local attempt
    for attempt in $(seq 1 30); do
        if curl -fsS -o /dev/null --max-time 2 http://127.0.0.1:${AI_MODE_PORT:-5005}/health/live; then
            log "AI-mode is live on the host (systemd)"
            return 0
        fi
        sleep 2
    done
    journalctl -u propertyscope-ai-mode --no-pager -n 20 || true
    die "AI-mode did not become live"
}

stop_ai_tier() {
    if systemctl list-unit-files propertyscope-ai.target >/dev/null 2>&1; then
        systemctl disable --now propertyscope-ai.target >/dev/null 2>&1 || true
        systemctl stop "${AI_UNITS[@]}" >/dev/null 2>&1 || true
    fi
    remove_ai_secrets
    printf 'false\n' >"$STATE_DIR/cloud-ai"
}

ai_toggle() {
    wait_for_bootstrap
    local wanted=$1
    export PROPERTYSCOPE_CLOUD_AI=$wanted
    if [[ $wanted == true ]]; then
        start_ai_tier
    else
        stop_ai_tier
    fi
    compose up --detach --wait --wait-timeout 300 --no-build --remove-orphans
    summary "ai-${wanted}"
}

# --- Observability ---------------------------------------------------------------------------

summary() {
    local action=$1 running total units=()
    running=$(compose ps --status running --quiet | wc -l)
    total=$(compose ps --all --quiet | wc -l)
    local unit
    for unit in "${AI_UNITS[@]}"; do
        units+=("\"${unit#propertyscope-}\":\"$(systemctl is-active "$unit" 2>/dev/null || true)\"")
    done
    local IFS=,
    printf 'PROPERTYSCOPE_RESULT={"action":"%s","image_tag":"%s","cloud_ai":"%s","containers_running":%s,"containers_total":%s,"ai_units":{%s}}\n' \
        "$action" "$(cat "$STATE_DIR/image-tag" 2>/dev/null || echo unknown)" "$(cloud_ai_state)" \
        "$running" "$total" "${units[*]}"
}

status() {
    compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Health}}\t{{.Ports}}'
    echo "Listening TCP sockets (expect 80/443 public; 5005 and loopback-only ports only with cloud AI):"
    ss -Htln | awk '{print "  " $4}' | sort -u
    summary status
}

logs() {
    local service=${PROPERTYSCOPE_LOG_SERVICE:-} lines=${PROPERTYSCOPE_LOG_LINES:-60}
    [[ $lines =~ ^[0-9]+$ ]] || die "PROPERTYSCOPE_LOG_LINES must be a number"
    case $service in
        ai-mode | mcp | rag | multi-agent)
            journalctl -u "propertyscope-${service}" --no-pager -n "$lines"
            ;;
        '')
            compose logs --no-color --tail "$lines"
            ;;
        *)
            [[ $service =~ ^[a-z0-9-]+$ ]] || die "invalid service name"
            compose logs --no-color --tail "$lines" "$service"
            ;;
    esac
}

# --- Data-security validation (R2-B6, on-host part) ---------------------------------------------

VALIDATION_FAILURES=0

check() {
    local description=$1
    shift
    if "$@"; then
        echo "PASS ${description}"
    else
        echo "FAIL ${description}"
        VALIDATION_FAILURES=$((VALIDATION_FAILURES + 1))
    fi
}

secrets_directory_is_private() { [[ $(stat -c '%a %U' "$SECRETS_DIR") == '700 root' ]]; }
no_writable_secret_files() { [[ -z $(find "$SECRETS_DIR" -type f -perm /022) ]]; }
network_is_internal() {
    [[ $(docker network inspect "${COMPOSE_PROJECT}_$1" --format '{{.Internal}}') == true ]]
}
container_publishes_nothing() { [[ -z $(docker port "${COMPOSE_PROJECT}-$1-1" 2>/dev/null) ]]; }
container_is_off_shared_network() {
    ! docker inspect "${COMPOSE_PROJECT}-$1-1" --format '{{json .NetworkSettings.Networks}}' |
        grep -q shared-platform
}
# Docker publishes 80/443 through iptables; anything else listening must be loopback-only, apart
# from the host AI entry points that containers reach through the host gateway.
only_expected_listeners() {
    [[ -z $(ss -Htln | awk '{print $4}' |
        grep -vE '^(127\.[0-9.]+|\[::1\]|127\.0\.0\.53%lo):[0-9]+$' |
        grep -vE ':(80|443|5005|5013)$') ]]
}
sshd_is_stopped() { ! systemctl is-active --quiet ssh.service; }
no_stored_registry_credential() { ! grep -q azurecr.io /root/.docker/config.json 2>/dev/null; }
count_is_zero() { [[ $1 -eq 0 ]]; }

validate_data() {
    local file value name leaked_env=0 leaked_history=0 inspect history containers
    check "secrets directory is root-only (0700)" secrets_directory_is_private
    check "no secret file is group/other writable" no_writable_secret_files
    # Every rendered secret value must be absent from container environments and image history.
    mapfile -t containers < <(docker ps --quiet)
    inspect=""
    if ((${#containers[@]})); then
        inspect=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "${containers[@]}")
    fi
    history=$(docker ps --format '{{.Image}}' | sort -u |
        xargs -r -n1 docker history --no-trunc --format '{{.CreatedBy}}' 2>/dev/null || true)
    for file in "$SECRETS_DIR"/*; do
        name=$(basename "$file")
        [[ -f $file && $name != edge-basic-auth && $name != *.env ]] || continue
        value=$(<"$file")
        [[ ${#value} -ge 12 ]] || continue
        if grep -qF -- "$value" <<<"$inspect"; then leaked_env=$((leaked_env + 1)); fi
        if grep -qF -- "$value" <<<"$history"; then leaked_history=$((leaked_history + 1)); fi
    done
    check "no secret value in any container environment (docker inspect)" count_is_zero "$leaked_env"
    check "no secret value in any image history layer" count_is_zero "$leaked_history"
    local network container
    for network in f1-data f2-data f3-data f4-data f5-data; do
        check "network ${network} is internal (no internet route)" network_is_internal "$network"
    done
    for container in f1-postgres f4-postgres f1-db-api f2-db-api f3-database f4-db-api f5-db-api; do
        check "${container} publishes no host port" container_publishes_nothing "$container"
        check "${container} is not on the shared network" container_is_off_shared_network "$container"
    done
    check "nothing but 80/443 (and host AI entry points) listens beyond loopback" only_expected_listeners
    check "sshd is not running" sshd_is_stopped
    check "Docker keeps no ACR credential after the pull" no_stored_registry_credential
    echo "PROPERTYSCOPE_RESULT={\"action\":\"validate-data\",\"failures\":${VALIDATION_FAILURES}}"
    [[ $VALIDATION_FAILURES -eq 0 ]]
}

main() {
    [[ $EUID -eq 0 ]] || die "run as root (az vm run-command does)"
    local action=${1:-}
    case $action in
        deploy) deploy ;;
        ai-on) ai_toggle true ;;
        ai-off) ai_toggle false ;;
        status) status ;;
        logs) logs ;;
        validate-data) validate_data ;;
        *) die "usage: propertyscope-vm.sh deploy|ai-on|ai-off|status|logs|validate-data" ;;
    esac
}

main "$@"
