#!/usr/bin/env bash
# Offline validation of the Azure Infrastructure as Code and edge configuration (ADR-048).
#
# Needs no Azure subscription, sign-in or network access to Azure: Bicep compiles locally, and the
# Caddy, nginx and cloud-init checks run in throwaway containers. Integration CI runs it with
# --strict in the `iac-lint` job; locally a missing tool is reported as SKIP.
#
#   deployment/azure/validate-iac.sh [--strict] [bicep|shell|caddy|nginx|cloud-init ...]
#
#   bicep       build and lint main.bicep and every module (warnings fail), and build both
#               parameter files with unset and empty environment values (GitHub passes an unset
#               repository variable as ''): the DNS label, region and VM size must never be empty
#   shell       shellcheck on deploy.sh, the VM script, the validators and the entrypoint shims
#   caddy       `caddy validate` with the AI tier and the site-wide login each off and on, and
#               `caddy fmt` (pinned image)
#   nginx       `nginx -t` of the shared edge with the production include, then a burst proving
#               the limit_req zone answers 429 on the B5 probe path
#   cloud-init  `cloud-init schema` on cloud-init.yaml (when cloud-init is installed)
#
# Tools: BICEP (default: bicep on PATH or ~/.azure/bin/bicep from `az bicep install`), Python,
# Docker (Caddy, nginx, and ShellCheck when it is not installed), cloud-init.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
readonly SCRIPT_DIR REPO_ROOT
readonly CADDY_IMAGE=caddy:2.10.2-alpine
readonly SHELLCHECK_IMAGE=koalaman/shellcheck:v0.11.0
readonly RATE_LIMIT_PROBE=/fragments/rate-limit-probe
readonly SHELL_SCRIPTS=(
    deployment/azure/deploy.sh
    deployment/azure/validate-iac.sh
    deployment/azure/validate-endpoint-security.sh
    deployment/azure/validate-data-security.sh
    deployment/azure/vm/propertyscope-vm.sh
    deployment/azure/rehearsal/vm/rehearsal.sh
    deployment/azure/compose/secret-env.sh
    deployment/azure/compose/18-propertyscope-secrets.envsh
    deployment/nginx/19-ai-mode-host.envsh
)

STRICT=false
FAILURES=0
SKIPS=0
WORK=$(mktemp -d)
CONTAINERS=()
cleanup() {
    if ((${#CONTAINERS[@]})); then
        docker rm -f "${CONTAINERS[@]}" >/dev/null 2>&1 || true
    fi
    rm -rf "$WORK"
}
trap cleanup EXIT

pass() { printf 'PASS %s\n' "$*"; }
fail() {
    printf 'FAIL %s\n' "$*"
    FAILURES=$((FAILURES + 1))
}
skip() {
    if [[ $STRICT == true ]]; then
        fail "$* (required with --strict)"
    else
        printf 'SKIP %s\n' "$*"
        SKIPS=$((SKIPS + 1))
    fi
}
have() { command -v "$1" >/dev/null 2>&1; }

# Docker on Windows (Git Bash) needs Windows paths for bind mounts.
host_path() {
    if have cygpath; then
        cygpath -w "$1"
    else
        printf '%s' "$1"
    fi
}

docker_ready() { have docker && docker info >/dev/null 2>&1; }

# --- Bicep ---------------------------------------------------------------------------------------

bicep_binary() {
    if [[ -n ${BICEP:-} ]]; then
        printf '%s' "$BICEP"
    elif have bicep; then
        command -v bicep
    elif [[ -x $HOME/.azure/bin/bicep ]]; then
        printf '%s' "$HOME/.azure/bin/bicep"
    elif [[ -x $HOME/.azure/bin/bicep.exe ]]; then
        printf '%s' "$HOME/.azure/bin/bicep.exe"
    fi
}

# Prints "<dnsLabel>|<location>|<vmSize>" for a parameter file in the current environment.
resolved_parameters() {
    "$1" build-params "$2" --stdout | "$PYTHON" -c '
import json, sys
document = json.load(sys.stdin)
values = {key: item.get("value") for key, item in json.loads(document["parametersJson"])["parameters"].items()}
print("|".join(str(values.get(key, "<default>")) for key in ("dnsLabel", "location", "vmSize")))
'
}

check_bicep() {
    local bicep file output resolved
    bicep=$(bicep_binary)
    if [[ -z $bicep ]]; then
        skip "Bicep (run 'az bicep install', or set BICEP)"
        return
    fi
    if output=$("$bicep" build "$SCRIPT_DIR/main.bicep" --stdout 2>&1 >/dev/null); [[ -z $output ]]; then
        pass "main.bicep compiles without diagnostics"
    else
        fail "main.bicep build diagnostics:"
        printf '%s\n' "$output"
    fi
    for file in "$SCRIPT_DIR/main.bicep" "$SCRIPT_DIR"/modules/*.bicep; do
        output=$("$bicep" lint "$file" 2>&1 || true)
        if [[ -z $output ]]; then
            pass "bicep lint ${file#"$REPO_ROOT"/}"
        else
            fail "bicep lint ${file#"$REPO_ROOT"/}:"
            printf '%s\n' "$output"
        fi
    done
    local candidate
    for candidate in python3 python; do
        # Skips the Windows Store python3 alias, which exists but does not run.
        if [[ -z ${PYTHON:-} ]] && have "$candidate" && "$candidate" -c 'import json' >/dev/null 2>&1; then
            PYTHON=$candidate
        fi
    done
    [[ -n ${PYTHON:-} ]] || {
        skip "Bicep parameter files (Python is needed to read build-params output)"
        return
    }
    local mode
    for file in main.bicepparam dev.bicepparam; do
        for mode in unset empty; do
            if ! resolved=$(
                export AZURE_VM_SSH_PUBLIC_KEY=unused
                if [[ $mode == unset ]]; then
                    unset AZURE_DNS_LABEL AZURE_LOCATION AZURE_VM_SIZE AZURE_ENCRYPTION_AT_HOST \
                        AZURE_DEPLOY_VM AZURE_MONTHLY_BUDGET AZURE_DEPLOY_BUDGET
                else
                    export AZURE_DNS_LABEL='' AZURE_LOCATION='' AZURE_VM_SIZE='' AZURE_ENCRYPTION_AT_HOST='' \
                        AZURE_DEPLOY_VM='' AZURE_MONTHLY_BUDGET='' AZURE_DEPLOY_BUDGET=''
                fi
                resolved_parameters "$bicep" "$SCRIPT_DIR/$file" 2>&1
            ); then
                fail "$file does not build with $mode variables: $resolved"
            elif [[ $resolved == *'||'* || $resolved == '|'* || $resolved == *'|' ]]; then
                fail "$file resolves an empty DNS label, region or VM size with $mode variables: $resolved"
            else
                pass "$file with $mode variables (dnsLabel|location|vmSize): $resolved"
            fi
        done
    done
}

# --- Shell ---------------------------------------------------------------------------------------

check_shell() {
    local script
    for script in "${SHELL_SCRIPTS[@]}"; do
        if bash -n "$REPO_ROOT/$script"; then
            pass "bash -n $script"
        else
            fail "bash -n $script"
        fi
    done
    local runner=()
    # The pinned image first, so CI and laptops report the same findings.
    if docker_ready; then
        runner=(docker run --rm -v "$(host_path "$REPO_ROOT"):/mnt:ro" -w /mnt "$SHELLCHECK_IMAGE")
    elif have shellcheck; then
        runner=(shellcheck)
    else
        skip "shellcheck (install it, or Docker)"
        return
    fi
    if (cd "$REPO_ROOT" && MSYS_NO_PATHCONV=1 "${runner[@]}" --severity=style --external-sources "${SHELL_SCRIPTS[@]}"); then
        pass "shellcheck (${runner[*]: -1})"
    else
        fail "shellcheck findings (above)"
    fi
}

# --- Caddy ---------------------------------------------------------------------------------------

check_caddy() {
    docker_ready || {
        skip "Caddy (needs Docker)"
        return
    }
    local hash mode site formatted
    hash=$(docker run --rm --network none "$CADDY_IMAGE" caddy hash-password --plaintext offline-validation | tail -n 1)
    printf 'propertyscope-operator %s\n' "$hash" >"$WORK/edge_basic_auth"
    printf 'propertyscope %s\npropertyscope-operator %s\n' "$hash" "$hash" >"$WORK/edge_site_auth"
    for mode in disabled enabled; do
        for site in on off; do
            if MSYS_NO_PATHCONV=1 docker run --rm --network none \
                -e PROPERTYSCOPE_PUBLIC_HOST=propertyscope-example.australiaeast.cloudapp.azure.com \
                -e PROPERTYSCOPE_ACME_EMAIL=operator@example.com \
                -v "$(host_path "$SCRIPT_DIR/Caddyfile"):/etc/caddy/Caddyfile:ro" \
                -v "$(host_path "$SCRIPT_DIR/caddy/ai-$mode.caddy"):/etc/caddy/propertyscope-ai.caddy:ro" \
                -v "$(host_path "$SCRIPT_DIR/caddy/site-auth-$site.caddy"):/etc/caddy/propertyscope-site-auth.caddy:ro" \
                -v "$(host_path "$WORK/edge_basic_auth"):/run/secrets/edge_basic_auth:ro" \
                -v "$(host_path "$WORK/edge_site_auth"):/run/secrets/edge_site_auth:ro" \
                "$CADDY_IMAGE" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >"$WORK/caddy.log" 2>&1; then
                pass "caddy validate (AI tier $mode, site login $site)"
            else
                fail "caddy validate (AI tier $mode, site login $site):"
                cat "$WORK/caddy.log"
            fi
        done
    done
    for formatted in Caddyfile caddy/ai-disabled.caddy caddy/ai-enabled.caddy caddy/site-auth-on.caddy caddy/site-auth-off.caddy; do
        docker run --rm -i --network none "$CADDY_IMAGE" caddy fmt - <"$SCRIPT_DIR/$formatted" >"$WORK/formatted"
        if diff -u "$SCRIPT_DIR/$formatted" "$WORK/formatted" >"$WORK/fmt.diff"; then
            pass "caddy fmt $formatted"
        else
            fail "caddy fmt $formatted (run caddy fmt --overwrite):"
            cat "$WORK/fmt.diff"
        fi
    done
}

# --- nginx ---------------------------------------------------------------------------------------

check_nginx() {
    docker_ready || {
        skip "nginx (needs Docker)"
        return
    }
    local image name port codes
    image=$(sed -n 's/^FROM \([^ ]*\).*/\1/p' "$REPO_ROOT/shared/frontend/Dockerfile" | head -n 1)
    name="propertyscope-iac-nginx-$$"
    CONTAINERS+=("$name")
    # The same files the shared-frontend image and docker-compose.azure.yml put in place.
    MSYS_NO_PATHCONV=1 docker run --detach --name "$name" --publish 127.0.0.1::8080 \
        -e AI_MODE_HOST=127.0.0.1 -e AI_MODE_PORT=9 -e AI_MODE_SERVICE_TOKEN= \
        -e 'NGINX_ENVSUBST_FILTER=AI_MODE_(HOST|PORT|SERVICE_TOKEN)' \
        -v "$(host_path "$REPO_ROOT/shared/frontend/nginx.conf"):/etc/nginx/templates/default.conf.template:ro" \
        -v "$(host_path "$REPO_ROOT/shared/frontend/generated/enabled-feature-routes.conf"):/usr/share/nginx/html/generated/enabled-feature-routes.conf:ro" \
        -v "$(host_path "$REPO_ROOT/deployment/nginx/19-ai-mode-host.envsh"):/docker-entrypoint.d/19-ai-mode-host.envsh:ro" \
        -v "$(host_path "$SCRIPT_DIR/nginx/00-propertyscope-production.conf"):/etc/nginx/conf.d/00-propertyscope-production.conf:ro" \
        "$image" >/dev/null
    for _ in $(seq 1 20); do
        docker exec "$name" test -f /etc/nginx/conf.d/default.conf 2>/dev/null && break
        sleep 0.5
    done
    if docker exec "$name" nginx -t >"$WORK/nginx.log" 2>&1; then
        pass "nginx -t with the production include ($image)"
    else
        fail "nginx -t with the production include:"
        cat "$WORK/nginx.log"
        return
    fi
    port=$(docker port "$name" 8080/tcp | sed -n 's/.*:\([0-9][0-9]*\)$/\1/p' | head -n 1)
    have curl || {
        skip "nginx rate-limit burst (needs curl)"
        return
    }
    # Same burst as validate-endpoint-security.sh (one curl process, 150 parallel transfers): the
    # probe must be answered after limit_req.
    mkdir -p "$WORK/burst"
    codes=$(curl --silent --parallel --parallel-immediate --parallel-max 50 --max-time 10 \
        --output "$WORK/burst/#1" --write-out '%{http_code}\n' \
        "http://127.0.0.1:${port}${RATE_LIMIT_PROBE}?burst=[1-150]" | sort | uniq -c | tr '\n' ' ')
    if [[ $codes =~ [0-9]+\ 429 ]]; then
        pass "burst on $RATE_LIMIT_PROBE is rate limited ($codes)"
    else
        fail "burst on $RATE_LIMIT_PROBE was never answered 429 ($codes)"
    fi
}

# --- cloud-init ----------------------------------------------------------------------------------

check_cloud_init() {
    if ! have cloud-init; then
        skip "cloud-init schema (install cloud-init)"
        return
    fi
    if cloud-init schema --config-file "$SCRIPT_DIR/cloud-init.yaml" --annotate; then
        pass "cloud-init schema cloud-init.yaml"
    else
        fail "cloud-init schema cloud-init.yaml"
    fi
}

main() {
    local checks=()
    while (($#)); do
        case $1 in
            --strict) STRICT=true ;;
            bicep | shell | caddy | nginx | cloud-init) checks+=("$1") ;;
            -h | --help)
                sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
                return 0
                ;;
            *)
                printf 'unknown argument: %s\n' "$1" >&2
                return 2
                ;;
        esac
        shift
    done
    ((${#checks[@]})) || checks=(bicep shell caddy nginx cloud-init)
    local check
    for check in "${checks[@]}"; do
        printf '== %s\n' "$check"
        "check_${check//-/_}"
    done
    printf 'IAC_VALIDATION_FAILURES=%s IAC_VALIDATION_SKIPS=%s\n' "$FAILURES" "$SKIPS"
    ((FAILURES == 0))
}

main "$@"
