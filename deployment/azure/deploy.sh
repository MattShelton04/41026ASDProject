#!/usr/bin/env bash
# PropertyScope NSW - Azure deployment operations (Release 2, ADR-048).
#
# One reusable entry point for a laptop (directly or through `uv run scripts/dev.py cloud ...`)
# and for .github/workflows/cloud-deployment.yml. Every subcommand is idempotent: re-running it
# converges the same resource group, images, VM state and AI flag.
#
#   deploy.sh [--dry-run] provision            resource group + Bicep (ACR, network, VM, Key Vault, RBAC, budget)
#   deploy.sh [--dry-run] secrets              create any missing Key Vault secrets (never overwrites)
#   deploy.sh [--dry-run] push                 build every enabled image and push it to ACR as :<git sha>
#   deploy.sh [--dry-run] deploy               converge the VM through `az vm run-command` (no SSH)
#   deploy.sh smoke [--output-dir DIR]         public smoke test (home, routes, health, CRUD, AI off)
#   deploy.sh [--dry-run] ai on|off            toggle the systemd host AI tier (bonus R2-B1..B4)
#   deploy.sh status | logs [SERVICE] [LINES]  container/AI state, recent logs (through run-command)
#   deploy.sh outputs                          print the Bicep outputs (fqdn, ACR, VM, Key Vault)
#   deploy.sh validate-endpoint | validate-data   bonus R2-B5 / R2-B6 validation scripts
#   deploy.sh all                              provision, push, deploy, smoke
#
# Configuration: environment variables, optionally from deployment/azure/.env.azure (the shell
# wins). See deployment/azure/.env.azure.example and deployment/azure/README.md. Nothing in this
# script reads or prints a secret value; the VM's managed identity reads Key Vault itself.
set -euo pipefail
umask 077

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
readonly SCRIPT_DIR REPO_ROOT
readonly DEPLOYMENT_NAME=propertyscope-main
readonly REQUIRED_SECRETS=(internal-token runner-token f1-postgres-password f4-postgres-password edge-basic-auth-password)
readonly AI_SECRETS=(ai-mode-service-token mcp-service-token rag-service-token multi-agent-service-token)
readonly MIRROR_IMAGES=("docker.io/library/caddy:2.10.2-alpine=propertyscope/mirror/caddy:2.10.2-alpine" "docker.io/postgis/postgis:16-3.4=propertyscope/mirror/postgis:16-3.4")
# Files the VM needs from this commit; images carry everything else.
readonly BUNDLE_PATHS=(
    docker-compose.yml
    docker-compose.azure.yml
    docker-compose.azure-ai.yml
    deployment/enabled-features.compose.yml
    deployment/enabled-features.v1.json
    deployment/azure/Caddyfile
    deployment/azure/caddy
    deployment/azure/nginx
    deployment/azure/compose
    deployment/azure/systemd
    deployment/azure/vm
)

DRY_RUN=${PROPERTYSCOPE_DRY_RUN:-false}

log() { printf '[deploy.sh %s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die() {
    printf '[deploy.sh] ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    sed -n '4,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# --- Configuration -----------------------------------------------------------------------------

load_env_file() {
    local file=${AZURE_ENV_FILE:-$SCRIPT_DIR/.env.azure} line key value
    [[ -f $file ]] || return 0
    while IFS= read -r line || [[ -n $line ]]; do
        line=${line%$'\r'}
        [[ -z $line || $line == \#* ]] && continue
        [[ $line == *=* ]] || continue
        key=${line%%=*}
        value=${line#*=}
        [[ $key =~ ^[A-Z][A-Z0-9_]*$ ]] || die "invalid variable name in $file: $key"
        # Strip one level of matching quotes; the file is data, never evaluated.
        if [[ $value =~ ^\"(.*)\"$ || $value =~ ^\'(.*)\'$ ]]; then
            value=${BASH_REMATCH[1]}
        fi
        if [[ -z ${!key+set} ]]; then
            export "$key=$value"
        fi
    done <"$file"
}

configure() {
    load_env_file
    export AZURE_LOCATION=${AZURE_LOCATION:-australiaeast}
    export AZURE_RESOURCE_GROUP=${AZURE_RESOURCE_GROUP:-rg-propertyscope-prod}
    export AZURE_PARAMETERS_FILE=${AZURE_PARAMETERS_FILE:-deployment/azure/main.bicepparam}
    export PROPERTYSCOPE_EDGE_USER=${PROPERTYSCOPE_EDGE_USER:-propertyscope-operator}
    export PROPERTYSCOPE_REPO_URL=${PROPERTYSCOPE_REPO_URL:-https://github.com/MattShelton04/41026ASDProject.git}
    LOG_DIR=${PROPERTYSCOPE_CLOUD_LOG_DIR:-$REPO_ROOT/.propertyscope-runtime/cloud}
    mkdir -p "$LOG_DIR"
    [[ $AZURE_RESOURCE_GROUP =~ ^[A-Za-z0-9._()-]{1,90}$ ]] || die "invalid AZURE_RESOURCE_GROUP"
    case ${PROPERTYSCOPE_CLOUD_AI:-} in
        '' | true | false) ;;
        *) die "PROPERTYSCOPE_CLOUD_AI must be true or false" ;;
    esac
}

# Images and the VM bundle are identified by the commit they were built from. A dirty working
# tree gets a distinct tag so a laptop experiment can never masquerade as a reviewed commit.
image_tag() {
    if [[ -n ${IMAGE_TAG:-} ]]; then
        [[ $IMAGE_TAG =~ ^[A-Za-z0-9_.-]{1,128}$ ]] || die "invalid IMAGE_TAG"
        printf '%s' "$IMAGE_TAG"
        return
    fi
    local sha
    sha=$(git -C "$REPO_ROOT" rev-parse HEAD)
    if [[ -n $(git -C "$REPO_ROOT" status --porcelain --untracked-files=no) ]]; then
        sha="${sha}-dirty"
    fi
    printf '%s' "$sha"
}

git_sha() {
    local tag
    tag=$(image_tag)
    printf '%s' "${PROPERTYSCOPE_GIT_SHA:-${tag%-dirty}}"
}

# --- Command execution -------------------------------------------------------------------------

# Mutating commands go through run(): printed and skipped in --dry-run.
run() {
    if [[ $DRY_RUN == true ]]; then
        printf '[dry-run]' >&2
        printf ' %q' "$@" >&2
        printf '\n' >&2
        return 0
    fi
    "$@"
}

require_tool() {
    local tool
    for tool in "$@"; do
        command -v "$tool" >/dev/null 2>&1 || die "$tool is required on PATH"
    done
}

# az is a native Windows program under Git Bash: hand it Windows paths for temporary files.
native_path() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
    else
        printf '%s' "$1"
    fi
}

az_query() {
    # Read-only Azure query; az prints CRLF on Windows.
    az "$@" | tr -d '\r'
}

ensure_azure_context() {
    if [[ $DRY_RUN == true ]]; then
        return 0
    fi
    require_tool az
    az account show --only-show-errors >/dev/null 2>&1 ||
        die "not signed in to Azure: run 'az login' (laptop) or azure/login (GitHub Actions)"
    if [[ -n ${AZURE_SUBSCRIPTION_ID:-} ]]; then
        az account set --subscription "$AZURE_SUBSCRIPTION_ID" --only-show-errors
    fi
}

# --- Outputs of the Bicep deployment -----------------------------------------------------------

load_outputs() {
    if [[ -n ${ACR_LOGIN_SERVER:-} && -n ${ACR_NAME:-} && -n ${VM_NAME:-} && -n ${KEY_VAULT_NAME:-} && -n ${PUBLIC_FQDN:-} ]]; then
        return 0
    fi
    if [[ $DRY_RUN == true ]]; then
        ACR_NAME=${ACR_NAME:-propertyscopeprodexample}
        ACR_LOGIN_SERVER=${ACR_LOGIN_SERVER:-${ACR_NAME}.azurecr.io}
        VM_NAME=${VM_NAME:-propertyscope-prod-vm}
        KEY_VAULT_NAME=${KEY_VAULT_NAME:-property-kv-example}
        PUBLIC_FQDN=${PUBLIC_FQDN:-propertyscope-nsw-g20.${AZURE_LOCATION}.cloudapp.azure.com}
        return 0
    fi
    local line
    line=$(az_query deployment group show --resource-group "$AZURE_RESOURCE_GROUP" --name "$DEPLOYMENT_NAME" \
        --query '[properties.outputs.acrName.value, properties.outputs.acrLoginServer.value, properties.outputs.vmName.value, properties.outputs.keyVaultName.value, properties.outputs.fqdn.value]' \
        --output tsv 2>/dev/null) || die "no '$DEPLOYMENT_NAME' deployment in $AZURE_RESOURCE_GROUP; run 'deploy.sh provision' first"
    read -r ACR_NAME ACR_LOGIN_SERVER VM_NAME KEY_VAULT_NAME PUBLIC_FQDN <<<"$line"
    [[ -n $PUBLIC_FQDN ]] || die "the Bicep outputs are incomplete; re-run 'deploy.sh provision'"
    export ACR_NAME ACR_LOGIN_SERVER VM_NAME KEY_VAULT_NAME PUBLIC_FQDN
}

cmd_outputs() {
    ensure_azure_context
    load_outputs
    printf 'resource_group=%s\nacr_name=%s\nacr_login_server=%s\nvm_name=%s\nkey_vault_name=%s\nfqdn=%s\npublic_url=https://%s\n' \
        "$AZURE_RESOURCE_GROUP" "$ACR_NAME" "$ACR_LOGIN_SERVER" "$VM_NAME" "$KEY_VAULT_NAME" "$PUBLIC_FQDN" "$PUBLIC_FQDN"
}

# --- provision ---------------------------------------------------------------------------------

budget_start_date() {
    if [[ -n ${AZURE_BUDGET_START_DATE:-} ]]; then
        printf '%s' "$AZURE_BUDGET_START_DATE"
        return
    fi
    local existing=""
    if [[ $DRY_RUN != true ]]; then
        # A budget's start date cannot move, so reuse the existing one; new budgets start this month.
        existing=$(az_query consumption budget list --resource-group "$AZURE_RESOURCE_GROUP" \
            --query "[?name=='${AZURE_NAME_PREFIX:-propertyscope}-prod-monthly'].timePeriod.start | [0]" \
            --output tsv 2>/dev/null || true)
    fi
    if [[ -n $existing && $existing != None ]]; then
        printf '%s' "${existing:0:10}"
    else
        date -u +%Y-%m-01
    fi
}

cmd_provision() {
    ensure_azure_context
    cd "$REPO_ROOT"
    [[ -f $AZURE_PARAMETERS_FILE ]] || die "parameters file not found: $AZURE_PARAMETERS_FILE"

    if [[ ${AZURE_ENCRYPTION_AT_HOST:-true} == true && $DRY_RUN != true ]]; then
        local state
        state=$(az_query feature show --namespace Microsoft.Compute --name EncryptionAtHost \
            --query properties.state --output tsv 2>/dev/null || echo Unknown)
        [[ $state == Registered ]] || die "encryption at host is not registered for this subscription (state: $state).
Run once: az feature register --namespace Microsoft.Compute --name EncryptionAtHost
then wait for 'Registered' and run: az provider register --namespace Microsoft.Compute
Or set AZURE_ENCRYPTION_AT_HOST=false (documented trade-off in deployment/azure/README.md)."
    fi

    if [[ $DRY_RUN == true ]] || ! az group show --name "$AZURE_RESOURCE_GROUP" --only-show-errors >/dev/null 2>&1; then
        log "Creating resource group $AZURE_RESOURCE_GROUP in $AZURE_LOCATION"
        run az group create --name "$AZURE_RESOURCE_GROUP" --location "$AZURE_LOCATION" \
            --tags application=propertyscope-nsw managed-by=deploy.sh --only-show-errors --output none
    else
        log "Resource group $AZURE_RESOURCE_GROUP already exists"
    fi

    local vm_name="${AZURE_NAME_PREFIX:-propertyscope}-prod-vm" key_dir=""
    if [[ $AZURE_PARAMETERS_FILE == *dev.bicepparam ]]; then
        vm_name="${AZURE_NAME_PREFIX:-propertyscope}-dev-vm"
    fi
    if [[ $DRY_RUN != true ]] && az vm show --resource-group "$AZURE_RESOURCE_GROUP" --name "$vm_name" --only-show-errors >/dev/null 2>&1; then
        # customData and the SSH key are immutable; later releases converge through run-command.
        export AZURE_DEPLOY_VM=false
        export AZURE_VM_SSH_PUBLIC_KEY=${AZURE_VM_SSH_PUBLIC_KEY:-unused-existing-vm}
        log "VM $vm_name exists: converging network, registry, vault, RBAC and budget only"
    else
        export AZURE_DEPLOY_VM=true
        if [[ -z ${AZURE_VM_SSH_PUBLIC_KEY:-} ]]; then
            # Azure requires a key for a Linux VM. No NSG rule admits SSH and cloud-init disables
            # sshd, so a throwaway key whose private half is deleted immediately is enough.
            require_tool ssh-keygen
            key_dir=$(mktemp -d)
            ssh-keygen -q -t ed25519 -N '' -C propertyscope-unused -f "$key_dir/id" >/dev/null
            AZURE_VM_SSH_PUBLIC_KEY=$(<"$key_dir/id.pub")
            export AZURE_VM_SSH_PUBLIC_KEY
            rm -rf "$key_dir"
        fi
    fi
    AZURE_BUDGET_START_DATE=$(budget_start_date)
    export AZURE_BUDGET_START_DATE

    log "Deploying $AZURE_PARAMETERS_FILE to $AZURE_RESOURCE_GROUP (deployment $DEPLOYMENT_NAME)"
    run az deployment group create \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --name "$DEPLOYMENT_NAME" \
        --parameters "$AZURE_PARAMETERS_FILE" \
        --only-show-errors --output none
    if [[ $DRY_RUN != true ]]; then
        cmd_outputs | tee "$LOG_DIR/outputs.txt"
    fi
}

# --- secrets (one-time operator step) ----------------------------------------------------------

random_token() {
    # 64 hex characters: valid for every PropertyScope service token ([A-Za-z0-9_-]{32,128}).
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

cmd_secrets() {
    ensure_azure_context
    load_outputs
    local name existing temporary opened=false
    if [[ -n ${KEY_VAULT_CLIENT_IP:-} ]]; then
        # The vault firewall denies the internet by default; admit this operator for the call only.
        [[ $KEY_VAULT_CLIENT_IP =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || die "KEY_VAULT_CLIENT_IP must be one IPv4 address"
        run az keyvault network-rule add --name "$KEY_VAULT_NAME" --ip-address "$KEY_VAULT_CLIENT_IP/32" --only-show-errors --output none
        opened=true
    fi
    temporary=$(mktemp)
    # shellcheck disable=SC2064 # expand now: the locals are gone when the EXIT trap runs
    trap "rm -f '$temporary'; if [[ $opened == true ]]; then run az keyvault network-rule remove --name '$KEY_VAULT_NAME' --ip-address '${KEY_VAULT_CLIENT_IP:-}/32' --only-show-errors --output none || true; fi" EXIT
    if [[ $opened == true && $DRY_RUN != true ]]; then
        sleep 20 # vault firewall changes take a few seconds to apply
    fi
    for name in "${REQUIRED_SECRETS[@]}" "${AI_SECRETS[@]}"; do
        existing=""
        if [[ $DRY_RUN != true ]]; then
            existing=$(az_query keyvault secret list --vault-name "$KEY_VAULT_NAME" \
                --query "[?name=='$name'].name | [0]" --output tsv 2>/dev/null) ||
                die "cannot list secrets in $KEY_VAULT_NAME: you need 'Key Vault Secrets Officer' (AZURE_SECRET_OFFICER_IDS) and network access (AZURE_OPERATOR_IP_RANGES or KEY_VAULT_CLIENT_IP)"
        fi
        if [[ -n $existing ]]; then
            log "Key Vault secret $name exists (kept)"
            continue
        fi
        random_token >"$temporary"
        run az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "$name" --file "$(native_path "$temporary")" \
            --encoding utf-8 --content-type text/plain --only-show-errors --output none
        log "Key Vault secret $name created with a random value"
    done
    if [[ -n ${OPENAI_API_KEY:-} ]]; then
        printf '%s' "$OPENAI_API_KEY" >"$temporary"
        run az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name openai-api-key --file "$(native_path "$temporary")" \
            --encoding utf-8 --content-type text/plain --only-show-errors --output none
        log "Key Vault secret openai-api-key set from OPENAI_API_KEY (only the cloud AI tier reads it)"
    fi
    : >"$temporary"
    log "Operator password for AI and operations routes: az keyvault secret show --vault-name $KEY_VAULT_NAME --name edge-basic-auth-password --query value -o tsv (user: $PROPERTYSCOPE_EDGE_USER)"
}

# --- push --------------------------------------------------------------------------------------

compose_base() {
    docker compose --project-directory "$REPO_ROOT" -f "$REPO_ROOT/docker-compose.yml" \
        -f "$REPO_ROOT/deployment/enabled-features.compose.yml" --profile release-0 "$@"
}

# Every enabled service built from this repository (image propertyscope/<service>:dev).
build_services() {
    compose_base config --images | tr -d '\r' | sed -n 's#^propertyscope/\([a-z0-9-]*\):dev$#\1#p' | sort -u
}

cmd_push() {
    ensure_azure_context
    load_outputs
    require_tool docker git
    local tag service services mirror source target
    tag=$(image_tag)
    mapfile -t services < <(build_services)
    ((${#services[@]})) || die "no buildable services found in the Compose model"
    log "Building ${#services[@]} images for $tag: ${services[*]}"
    run az acr login --name "$ACR_NAME" --only-show-errors
    run compose_base build --pull "${services[@]}"
    for service in "${services[@]}"; do
        target="$ACR_LOGIN_SERVER/propertyscope/$service:$tag"
        run docker tag "propertyscope/$service:dev" "$target"
        run docker push --quiet "$target"
        log "Pushed $target"
    done
    # Third-party images are imported once into ACR so the VM pulls only from the private registry.
    for mirror in "${MIRROR_IMAGES[@]}"; do
        source=${mirror%%=*}
        target=${mirror#*=}
        if [[ $DRY_RUN != true ]] && az acr repository show --name "$ACR_NAME" --image "$target" --only-show-errors >/dev/null 2>&1; then
            log "Mirror $target already in ACR"
            continue
        fi
        run az acr import --name "$ACR_NAME" --source "$source" --image "$target" --force --only-show-errors
        log "Imported $source as $target"
    done
    printf '%s\n' "$tag" >"$LOG_DIR/image-tag.txt"
}

# --- VM operations through run-command ---------------------------------------------------------

bundle_base64() {
    local path
    for path in "${BUNDLE_PATHS[@]}"; do
        [[ -e $REPO_ROOT/$path ]] || die "bundle input missing: $path"
    done
    tar -C "$REPO_ROOT" -czf - "${BUNDLE_PATHS[@]}" | base64 | tr -d '\n\r'
}

# Builds the run-command script: non-secret settings, the deployment bundle and one action.
vm_payload() {
    local action=$1 bundle variable
    bundle=$(bundle_base64)
    printf '%s\n' '#!/bin/bash' 'set -euo pipefail' 'umask 022'
    for variable in ACR_LOGIN_SERVER IMAGE_TAG KEY_VAULT_NAME PROPERTYSCOPE_PUBLIC_HOST PROPERTYSCOPE_ACME_EMAIL \
        PROPERTYSCOPE_CLOUD_AI PROPERTYSCOPE_GIT_SHA PROPERTYSCOPE_REPO_URL PROPERTYSCOPE_EDGE_USER \
        PROPERTYSCOPE_FORCE_RECREATE PROPERTYSCOPE_LOG_SERVICE PROPERTYSCOPE_LOG_LINES PROPERTYSCOPE_SEED_FIXTURE; do
        if [[ -n ${!variable:-} ]]; then
            printf 'export %s=%q\n' "$variable" "${!variable}"
        fi
    done
    cat <<EOF
install -d -m 0755 /opt/propertyscope/app
rm -rf /opt/propertyscope/app/deployment /opt/propertyscope/app/docker-compose*.yml
printf '%s' '$bundle' | base64 -d | tar -xzf - -C /opt/propertyscope/app --no-same-owner
chmod 0755 /opt/propertyscope/app/deployment/azure/vm/*.sh /opt/propertyscope/app/deployment/azure/compose/*
status=0
bash /opt/propertyscope/app/deployment/azure/vm/propertyscope-vm.sh $action || status=\$?
echo "PROPERTYSCOPE_EXIT=\$status"
exit "\$status"
EOF
}

ensure_vm_running() {
    if [[ $DRY_RUN == true ]]; then
        return 0
    fi
    local power
    power=$(az_query vm get-instance-view --resource-group "$AZURE_RESOURCE_GROUP" --name "$VM_NAME" \
        --query "instanceView.statuses[?starts_with(code, 'PowerState/')].code | [0]" --output tsv)
    if [[ $power != PowerState/running ]]; then
        # The daily auto-shutdown deallocates the VM; deployments start it again.
        log "VM $VM_NAME is ${power#PowerState/}; starting it"
        az vm start --resource-group "$AZURE_RESOURCE_GROUP" --name "$VM_NAME" --only-show-errors --output none
    fi
}

vm_run() {
    local action=$1 payload message exit_code
    ensure_vm_running
    payload=$(mktemp)
    vm_payload "$action" >"$payload"
    if [[ $DRY_RUN == true ]]; then
        log "[dry-run] would run '$action' on $VM_NAME through az vm run-command invoke ($(wc -c <"$payload") byte payload)"
        cp "$payload" "$LOG_DIR/vm-$action.payload.sh"
        rm -f "$payload"
        return 0
    fi
    log "Running '$action' on $VM_NAME through az vm run-command invoke"
    message=$(az_query vm run-command invoke --resource-group "$AZURE_RESOURCE_GROUP" --name "$VM_NAME" \
        --command-id RunShellScript --scripts "@$(native_path "$payload")" --query 'value[0].message' --output tsv)
    rm -f "$payload"
    printf '%s\n' "$message" | tee "$LOG_DIR/vm-$action.log"
    # run-command reports success even when the script fails; the payload prints its exit status.
    exit_code=$(sed -n 's/^PROPERTYSCOPE_EXIT=\([0-9]*\)$/\1/p' <<<"$message" | tail -n 1)
    [[ -n $exit_code ]] || die "'$action' did not report an exit status (output truncated or the VM agent failed)"
    [[ $exit_code == 0 ]] || die "'$action' failed on the VM with exit status $exit_code (see $LOG_DIR/vm-$action.log)"
}

vm_environment() {
    load_outputs
    IMAGE_TAG=$(image_tag)
    PROPERTYSCOPE_PUBLIC_HOST=${PROPERTYSCOPE_PUBLIC_HOST:-$PUBLIC_FQDN}
    [[ -n ${PROPERTYSCOPE_ACME_EMAIL:-} ]] || die "PROPERTYSCOPE_ACME_EMAIL is required (certificate expiry notices)"
    PROPERTYSCOPE_GIT_SHA=$(git_sha)
    export IMAGE_TAG PROPERTYSCOPE_PUBLIC_HOST PROPERTYSCOPE_GIT_SHA
}

cmd_deploy() {
    ensure_azure_context
    vm_environment
    if [[ $DRY_RUN != true ]]; then
        az acr repository show --name "$ACR_NAME" --image "propertyscope/shared-frontend:$IMAGE_TAG" --only-show-errors >/dev/null 2>&1 ||
            die "ACR has no images for $IMAGE_TAG; run 'deploy.sh push' first"
    fi
    vm_run deploy
    printf '%s\n' "https://$PROPERTYSCOPE_PUBLIC_HOST" >"$LOG_DIR/public-url.txt"
    log "Deployed $IMAGE_TAG to https://$PROPERTYSCOPE_PUBLIC_HOST"
}

cmd_ai() {
    local wanted=${1:-}
    case $wanted in
        on) export PROPERTYSCOPE_CLOUD_AI=true ;;
        off) export PROPERTYSCOPE_CLOUD_AI=false ;;
        *) die "usage: deploy.sh ai on|off" ;;
    esac
    ensure_azure_context
    vm_environment
    vm_run "ai-$wanted"
}

cmd_status() {
    ensure_azure_context
    vm_environment
    vm_run status
}

cmd_logs() {
    local service=${1:-} lines=${2:-80}
    [[ -z $service || $service =~ ^[a-z0-9-]+$ ]] || die "invalid service name"
    [[ $lines =~ ^[0-9]+$ ]] || die "LINES must be a number"
    export PROPERTYSCOPE_LOG_SERVICE=$service PROPERTYSCOPE_LOG_LINES=$lines
    ensure_azure_context
    vm_environment
    vm_run logs
}

# --- smoke and validation ----------------------------------------------------------------------

python_runner() {
    if command -v uv >/dev/null 2>&1; then
        printf 'uv run --locked python'
    else
        printf 'python3'
    fi
}

public_base_url() {
    if [[ -n ${PROPERTYSCOPE_PUBLIC_URL:-} ]]; then
        printf '%s' "${PROPERTYSCOPE_PUBLIC_URL%/}"
        return
    fi
    ensure_azure_context
    load_outputs
    printf 'https://%s' "$PUBLIC_FQDN"
}

cmd_smoke() {
    local output_dir="$LOG_DIR/smoke" base_url runner
    local extra=()
    while (($#)); do
        case $1 in
            --output-dir)
                output_dir=$2
                shift 2
                ;;
            --expect-ai)
                extra+=(--expect-ai)
                shift
                ;;
            *) die "unknown smoke option: $1" ;;
        esac
    done
    base_url=$(public_base_url)
    runner=$(python_runner)
    cd "$REPO_ROOT"
    # shellcheck disable=SC2086 # the runner is a fixed, trusted command prefix
    run $runner scripts/cloud_smoke.py --base-url "$base_url" --output-dir "$output_dir" "${extra[@]}"
}

cmd_validate() {
    local which=$1
    ensure_azure_context
    load_outputs
    export AZURE_RESOURCE_GROUP ACR_NAME VM_NAME KEY_VAULT_NAME PUBLIC_FQDN LOG_DIR
    run bash "$SCRIPT_DIR/validate-$which-security.sh"
}

main() {
    local argument
    while (($#)); do
        case $1 in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            -h | --help)
                usage
                return 0
                ;;
            *) break ;;
        esac
    done
    argument=${1:-}
    [[ -n $argument ]] || {
        usage
        return 2
    }
    shift
    configure
    export DRY_RUN
    case $argument in
        provision) cmd_provision ;;
        secrets) cmd_secrets ;;
        push) cmd_push ;;
        deploy) cmd_deploy ;;
        smoke) cmd_smoke "$@" ;;
        ai) cmd_ai "$@" ;;
        status) cmd_status ;;
        logs) cmd_logs "$@" ;;
        outputs) cmd_outputs ;;
        validate-endpoint) cmd_validate endpoint ;;
        validate-data) cmd_validate data ;;
        all)
            cmd_provision
            cmd_push
            cmd_deploy
            cmd_smoke
            ;;
        *)
            usage
            die "unknown command: $argument"
            ;;
    esac
}

main "$@"
