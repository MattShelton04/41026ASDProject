#!/usr/bin/env bash
# PropertyScope NSW - Azure deployment operations (Release 2, ADR-048).
#
# One reusable entry point for a laptop (directly or through `uv run scripts/dev.py cloud ...`)
# and for .github/workflows/cloud-deployment.yml. Every subcommand is idempotent: re-running it
# converges the same resource group, images, VM state and AI flag.
#
#   deploy.sh [--dry-run] provision            resource group + Bicep (ACR, network, VM, Key Vault, RBAC, budget)
#   deploy.sh [--dry-run] secrets              create any missing Key Vault secrets (never overwrites)
#   deploy.sh [--dry-run] push [--reuse-images]   build every enabled image and push it to ACR as :<git sha>
#   deploy.sh [--dry-run] deploy               converge the VM through `az vm run-command` (no SSH)
#   deploy.sh smoke [--output-dir DIR] [--expect-ai] [--insecure]   public smoke test (home, routes, health, CRUD, AI off)
#   deploy.sh [--dry-run] ai on|off            toggle the systemd host AI tier (bonus R2-B1..B4)
#   deploy.sh status | logs [SERVICE] [LINES]  container/AI state, recent logs (through run-command)
#   deploy.sh outputs                          print the Bicep outputs (fqdn, ACR, VM, Key Vault)
#   deploy.sh validate-endpoint | validate-data   bonus R2-B5 / R2-B6 validation scripts
#   deploy.sh all                              provision, push, deploy, smoke
#
# Configuration: environment variables, optionally from deployment/azure/.env.azure (the shell
# wins). See deployment/azure/.env.azure.example and deployment/azure/README.md. Nothing in this
# script reads or prints a secret value; the VM's managed identity reads Key Vault itself.
#
# Local rehearsal: with PROPERTYSCOPE_REHEARSAL=true (set by `uv run scripts/dev.py cloud
# rehearse`), push, deploy, smoke, status, logs, validate-endpoint and vm-validate-data target a
# local registry and a Docker-in-Docker rehearsal VM instead of Azure; every az call is refused.
set -euo pipefail
umask 077

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
readonly SCRIPT_DIR REPO_ROOT
readonly DEPLOYMENT_NAME=propertyscope-main
readonly REQUIRED_SECRETS=(internal-token runner-token f1-postgres-password f4-postgres-password edge-basic-auth-password edge-site-password)
# The site-wide viewer login (PROPERTYSCOPE_SITE_AUTH=on) and the temporary NSG rule that lets this
# machine reach HTTPS for the smoke test and endpoint validation when 443 is limited to a list.
readonly SITE_PASSWORD_SECRET=edge-site-password
readonly TEMPORARY_HTTPS_RULE=AllowDeployerHttpsTemporary
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
REHEARSAL=${PROPERTYSCOPE_REHEARSAL:-false}

log() { printf '[deploy.sh %s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die() {
    printf '[deploy.sh] ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    sed -n '4,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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
    case $REHEARSAL in
        true | false) ;;
        *) die "PROPERTYSCOPE_REHEARSAL must be true or false" ;;
    esac
    if [[ $REHEARSAL == true ]]; then
        # The rehearsal never reads .env.azure: it must not pick up a real subscription's settings.
        configure_rehearsal
    else
        load_env_file
    fi
    export AZURE_LOCATION=${AZURE_LOCATION:-australiaeast}
    export AZURE_RESOURCE_GROUP=${AZURE_RESOURCE_GROUP:-rg-propertyscope-prod}
    export AZURE_PARAMETERS_FILE=${AZURE_PARAMETERS_FILE:-deployment/azure/main.bicepparam}
    export PROPERTYSCOPE_EDGE_USER=${PROPERTYSCOPE_EDGE_USER:-propertyscope-operator}
    export PROPERTYSCOPE_SITE_AUTH=${PROPERTYSCOPE_SITE_AUTH:-on}
    export PROPERTYSCOPE_SITE_USER=${PROPERTYSCOPE_SITE_USER:-propertyscope}
    [[ $PROPERTYSCOPE_SITE_AUTH == on || $PROPERTYSCOPE_SITE_AUTH == off ]] || die "PROPERTYSCOPE_SITE_AUTH must be on or off"
    [[ $PROPERTYSCOPE_SITE_USER =~ ^[a-z][a-z0-9._-]{2,31}$ ]] || die "PROPERTYSCOPE_SITE_USER must be 3-32 lower-case characters"
    [[ $PROPERTYSCOPE_SITE_USER != "$PROPERTYSCOPE_EDGE_USER" ]] || die "PROPERTYSCOPE_SITE_USER must differ from PROPERTYSCOPE_EDGE_USER"
    export PROPERTYSCOPE_REPO_URL=${PROPERTYSCOPE_REPO_URL:-https://github.com/MattShelton04/41026ASDProject.git}
    if [[ $REHEARSAL == true ]]; then
        LOG_DIR=${PROPERTYSCOPE_CLOUD_LOG_DIR:-$REPO_ROOT/.propertyscope-runtime/cloud-rehearsal/cloud}
    else
        LOG_DIR=${PROPERTYSCOPE_CLOUD_LOG_DIR:-$REPO_ROOT/.propertyscope-runtime/cloud}
    fi
    mkdir -p "$LOG_DIR"
    [[ $AZURE_RESOURCE_GROUP =~ ^[A-Za-z0-9._()-]{1,90}$ ]] || die "invalid AZURE_RESOURCE_GROUP"
    case ${PROPERTYSCOPE_CLOUD_AI:-} in
        '' | true | false) ;;
        *) die "PROPERTYSCOPE_CLOUD_AI must be true or false" ;;
    esac
    if [[ $REHEARSAL == true ]]; then
        refuse_azure_in_child_processes
    fi
}

# --- Local rehearsal (`dev.py cloud rehearse`) ---------------------------------------------------

# A registry container stands in for ACR and a Docker-in-Docker container for the VM. The operator
# pushes to the registry's loopback port; the rehearsal VM pulls from it by its container name
# (ACR_LOGIN_SERVER), so both names address the same registry.
configure_rehearsal() {
    [[ ${PROPERTYSCOPE_REHEARSAL_VM:-} =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] ||
        die "PROPERTYSCOPE_REHEARSAL_VM must name the rehearsal VM container (dev.py cloud rehearse sets it)"
    [[ ${PROPERTYSCOPE_PUSH_REGISTRY:-} =~ ^(127\.0\.0\.1|localhost):[0-9]{1,5}$ ]] ||
        die "the rehearsal pushes only to a loopback registry (PROPERTYSCOPE_PUSH_REGISTRY=127.0.0.1:<port>)"
}

# Every az call fails in a rehearsal: this shell gets an az function, and child processes (the
# validation scripts) find a refusing az first on PATH.
refuse_azure_in_child_processes() {
    local bin="$LOG_DIR/.rehearsal-bin"
    mkdir -p "$bin"
    printf '%s\n' '#!/usr/bin/env bash' 'echo "rehearsal: az is disabled (no Azure in a local rehearsal)" >&2' 'exit 97' >"$bin/az"
    chmod 0755 "$bin/az"
    if command -v cygpath >/dev/null 2>&1; then
        bin=$(cygpath -u "$bin") # C:/... would split PATH at the drive colon under Git Bash
    fi
    export PATH="$bin:$PATH"
}

# Git Bash (MSYS) rewrites native-program arguments that look like POSIX paths, so an Azure
# resource ID such as /subscriptions/... would reach az as C:/Program Files/Git/subscriptions/...
# Every az call here turns that off; file arguments go through native_path explicitly instead.
az() {
    if [[ $REHEARSAL == true ]]; then
        die "the local rehearsal never calls Azure (refused: az ${1:-})"
    fi
    MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' command az "$@"
}

push_registry() {
    if [[ $REHEARSAL == true ]]; then
        printf '%s' "$PROPERTYSCOPE_PUSH_REGISTRY"
    else
        printf '%s' "$ACR_LOGIN_SERVER"
    fi
}

# True when the rehearsal registry holds the manifest (registry v2 API, anonymous).
registry_has_image() {
    curl -fsS -o /dev/null --max-time 15 \
        -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json' \
        "http://$(push_registry)/v2/$1/manifests/$2"
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
        type -P "$tool" >/dev/null 2>&1 || die "$tool is required on PATH"
    done
}

# az is a native Windows program under Git Bash and az() turns off automatic path conversion:
# hand it Windows paths for every file argument.
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
    if [[ $DRY_RUN == true || $REHEARSAL == true ]]; then
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

outputs_known() {
    [[ -n ${ACR_LOGIN_SERVER:-} && -n ${ACR_NAME:-} && -n ${VM_NAME:-} && -n ${KEY_VAULT_NAME:-} && -n ${PUBLIC_FQDN:-} ]]
}

load_outputs() {
    if outputs_known; then
        return 0
    fi
    if [[ $REHEARSAL == true ]]; then
        die "a rehearsal names its stand-ins itself: set ACR_LOGIN_SERVER, ACR_NAME, VM_NAME, KEY_VAULT_NAME and PUBLIC_FQDN"
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

environment_name() {
    if [[ $AZURE_PARAMETERS_FILE == *dev.bicepparam ]]; then
        printf 'dev'
    else
        printf 'prod'
    fi
}

# Purge protection keeps a deleted vault, and its name, for the retention period (7 days), and the
# vault name is derived from the resource group ID. Tearing the group down and provisioning it
# again within that window would therefore collide with the soft-deleted vault. Recover it
# instead, which also brings its secrets back. A fresh empty vault needs AZURE_KEY_VAULT_NAME_SEED.
recover_deleted_key_vault() {
    if [[ -n ${AZURE_KEY_VAULT_NAME_SEED:-} ]]; then
        return 0
    fi
    if [[ $DRY_RUN == true ]]; then
        log "[dry-run] would recover a soft-deleted PropertyScope Key Vault from $AZURE_RESOURCE_GROUP, if any"
        return 0
    fi
    local listing prefix rg_path name vault_id environment candidates=()
    prefix="${AZURE_NAME_PREFIX:-propertyscope}"
    prefix="${prefix:0:8}-kv-"
    rg_path=$(printf '/resourcegroups/%s/providers/microsoft.keyvault/vaults/' "$AZURE_RESOURCE_GROUP" | tr '[:upper:]' '[:lower:]')
    # Listing deleted vaults is a subscription-scope read; a resource-group-scoped deployer cannot.
    if ! listing=$(az_query keyvault list-deleted --resource-type vault \
        --query "[?properties.location=='${AZURE_LOCATION}'].[name, properties.vaultId, properties.tags.environment]" \
        --output tsv 2>/dev/null); then
        log "Could not list soft-deleted Key Vaults (needs subscription-level read); skipping the recovery check"
        return 0
    fi
    while IFS=$'\t' read -r name vault_id environment; do
        [[ -n $name && $name == "$prefix"* ]] || continue
        [[ $(tr '[:upper:]' '[:lower:]' <<<"$vault_id") == *"$rg_path"* ]] || continue
        [[ -z $environment || $environment == None || $environment == "$(environment_name)" ]] || continue
        candidates+=("$name")
    done <<<"$listing"
    case ${#candidates[@]} in
        0) return 0 ;;
        1)
            log "Recovering soft-deleted Key Vault ${candidates[0]} (purge protection keeps it after a teardown)"
            run az keyvault recover --name "${candidates[0]}" --resource-group "$AZURE_RESOURCE_GROUP" \
                --location "$AZURE_LOCATION" --only-show-errors --output none
            ;;
        *) die "several soft-deleted Key Vaults from $AZURE_RESOURCE_GROUP (${candidates[*]}): recover the right one with 'az keyvault recover --name <vault>', or set AZURE_KEY_VAULT_NAME_SEED for a fresh vault" ;;
    esac
}

cmd_provision() {
    ensure_azure_context
    cd "$REPO_ROOT"
    [[ -f $AZURE_PARAMETERS_FILE ]] || die "parameters file not found: $AZURE_PARAMETERS_FILE"

    if [[ ${AZURE_ENCRYPTION_AT_HOST:-true} == true && $DRY_RUN != true ]]; then
        local state
        state=$(az_query feature show --namespace Microsoft.Compute --name EncryptionAtHost \
            --query properties.state --output tsv 2>/dev/null || echo Unknown)
        # A resource-group-scoped deployer cannot read subscription features; ARM then reports
        # an unregistered feature itself, so only a definite answer stops here.
        [[ $state == Registered || $state == Unknown ]] || die "encryption at host is not registered for this subscription (state: $state).
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
    recover_deleted_key_vault

    local vm_name key_dir=""
    vm_name="${AZURE_NAME_PREFIX:-propertyscope}-$(environment_name)-vm"
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
        --parameters "$(native_path "$AZURE_PARAMETERS_FILE")" \
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
        if [[ $name == "$SITE_PASSWORD_SECRET" && -n ${PROPERTYSCOPE_SITE_PASSWORD:-} ]]; then
            # A password chosen to hand to markers; it must still resist guessing.
            ((${#PROPERTYSCOPE_SITE_PASSWORD} >= 12)) || die "PROPERTYSCOPE_SITE_PASSWORD must be at least 12 characters"
            printf '%s' "$PROPERTYSCOPE_SITE_PASSWORD" >"$temporary"
        else
            random_token >"$temporary"
        fi
        run az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "$name" --file "$(native_path "$temporary")" \
            --encoding utf-8 --content-type text/plain --only-show-errors --output none
        log "Key Vault secret $name created"
    done
    if [[ -n ${OPENAI_API_KEY:-} ]]; then
        printf '%s' "$OPENAI_API_KEY" >"$temporary"
        run az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name openai-api-key --file "$(native_path "$temporary")" \
            --encoding utf-8 --content-type text/plain --only-show-errors --output none
        log "Key Vault secret openai-api-key set from OPENAI_API_KEY (only the cloud AI tier reads it)"
    fi
    : >"$temporary"
    log "Operator password for AI and operations routes: az keyvault secret show --vault-name $KEY_VAULT_NAME --name edge-basic-auth-password --query value -o tsv (user: $PROPERTYSCOPE_EDGE_USER)"
    log "Site-wide viewer login (PROPERTYSCOPE_SITE_AUTH=$PROPERTYSCOPE_SITE_AUTH): user $PROPERTYSCOPE_SITE_USER, password in the Key Vault secret $SITE_PASSWORD_SECRET (read it like the operator password). The operator login also opens the site."
    log "Give GitHub Actions the same value for the smoke test: gh secret set PROPERTYSCOPE_SITE_PASSWORD --env production"
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

# The local tag images are built under. `dev` is what the developer stack runs; the rehearsal
# builds under its own tag so the shared propertyscope/<service>:dev images stay untouched.
build_image_tag() {
    local tag=${PROPERTYSCOPE_BUILD_TAG:-dev}
    [[ $tag =~ ^[A-Za-z0-9_.-]{1,128}$ ]] || die "invalid PROPERTYSCOPE_BUILD_TAG"
    printf '%s' "$tag"
}

build_images() {
    local build_tag=$1 override service
    shift
    if [[ $build_tag == dev ]]; then
        run compose_base build --pull "$@"
        return
    fi
    override="$LOG_DIR/build-tag.compose.yml"
    {
        printf '# Written by deploy.sh push: build under propertyscope/<service>:%s.\nservices:\n' "$build_tag"
        for service in "$@"; do
            printf '  %s:\n    image: propertyscope/%s:%s\n' "$service" "$service" "$build_tag"
        done
    } >"$override"
    run compose_base -f "$override" build --pull "$@"
}

# --reuse-images skips the build only for images this script built for the same tag on this
# machine (their IDs are recorded in a build manifest), and never for a "-dirty" tag, whose
# content can change while the tag stays the same. Anything else could push stale images under a
# reviewed commit's tag.
build_manifest() {
    printf '%s/%s.%s.images' "${PROPERTYSCOPE_BUILD_MANIFEST_DIR:-$REPO_ROOT/.propertyscope-runtime/cloud-builds}" "$1" "$2"
}

record_build_manifest() {
    local tag=$1 build_tag=$2 manifest service id
    shift 2
    [[ $DRY_RUN != true ]] || return 0
    manifest=$(build_manifest "$tag" "$build_tag")
    mkdir -p "${manifest%/*}"
    for service in "$@"; do
        id=$(docker image inspect --format '{{.Id}}' "propertyscope/$service:$build_tag" | tr -d '\r')
        printf '%s %s\n' "$service" "$id"
    done >"$manifest.tmp"
    mv -f "$manifest.tmp" "$manifest"
}

verify_reusable_images() {
    local tag=$1 build_tag=$2 manifest service expected id
    shift 2
    [[ $tag != *-dirty ]] || die "--reuse-images needs a committed tree: the tag $tag does not identify the image content"
    manifest=$(build_manifest "$tag" "$build_tag")
    [[ -f $manifest ]] || die "--reuse-images: nothing was built for $tag on this machine; run push without it"
    for service in "$@"; do
        expected=$(awk -v service="$service" '$1 == service { print $2 }' "$manifest")
        id=$(docker image inspect --format '{{.Id}}' "propertyscope/$service:$build_tag" 2>/dev/null | tr -d '\r' || true)
        [[ -n $expected && $id == "$expected" ]] ||
            die "--reuse-images: propertyscope/$service:$build_tag is not the image built for $tag; run push without --reuse-images"
    done
    log "Reusing the $# images built for $tag (manifest ${manifest#"$REPO_ROOT"/})"
}

cmd_push() {
    local reuse=${PROPERTYSCOPE_PUSH_REUSE_IMAGES:-false}
    while (($#)); do
        case $1 in
            --reuse-images)
                reuse=true
                shift
                ;;
            *) die "unknown push option: $1" ;;
        esac
    done
    [[ $reuse == true || $reuse == false ]] || die "PROPERTYSCOPE_PUSH_REUSE_IMAGES must be true or false"
    ensure_azure_context
    load_outputs
    require_tool docker git
    local tag build_tag registry service services mirror source target
    tag=$(image_tag)
    build_tag=$(build_image_tag)
    registry=$(push_registry)
    mapfile -t services < <(build_services)
    ((${#services[@]})) || die "no buildable services found in the Compose model"
    if [[ $REHEARSAL != true ]]; then
        run az acr login --name "$ACR_NAME" --only-show-errors
    fi
    if [[ $reuse == true ]]; then
        verify_reusable_images "$tag" "$build_tag" "${services[@]}"
    else
        log "Building ${#services[@]} images for $tag: ${services[*]}"
        build_images "$build_tag" "${services[@]}"
        record_build_manifest "$tag" "$build_tag" "${services[@]}"
    fi
    for service in "${services[@]}"; do
        target="$registry/propertyscope/$service:$tag"
        run docker tag "propertyscope/$service:$build_tag" "$target"
        run docker push --quiet "$target"
        log "Pushed $target"
    done
    # Third-party images are imported once into ACR so the VM pulls only from the private registry.
    for mirror in "${MIRROR_IMAGES[@]}"; do
        source=${mirror%%=*}
        target=${mirror#*=}
        if [[ $REHEARSAL == true ]]; then
            # The rehearsal registry cannot import: pull, tag and push the same pinned image.
            run docker pull --quiet "$source"
            run docker tag "$source" "$registry/$target"
            run docker push --quiet "$registry/$target"
            log "Mirrored $source as $registry/$target"
            continue
        fi
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
    local action=$1 variable
    printf '%s\n' '#!/bin/bash' 'set -euo pipefail' 'umask 022'
    for variable in ACR_LOGIN_SERVER IMAGE_TAG KEY_VAULT_NAME PROPERTYSCOPE_PUBLIC_HOST PROPERTYSCOPE_ACME_EMAIL \
        PROPERTYSCOPE_CLOUD_AI PROPERTYSCOPE_GIT_SHA PROPERTYSCOPE_REPO_URL PROPERTYSCOPE_EDGE_USER \
        PROPERTYSCOPE_SITE_AUTH PROPERTYSCOPE_SITE_USER \
        PROPERTYSCOPE_FORCE_RECREATE PROPERTYSCOPE_LOG_SERVICE PROPERTYSCOPE_LOG_LINES PROPERTYSCOPE_SEED_FIXTURE \
        PROPERTYSCOPE_AUTH_RETRY_ATTEMPTS PROPERTYSCOPE_STARTUP_WAIT_SECONDS; do
        if [[ -n ${!variable:-} ]]; then
            printf 'export %s=%q\n' "$variable" "${!variable}"
        fi
    done
    case $action in
        deploy | ai-on | ai-off)
            # Changing actions ship this commit's Compose files and edge/VM configuration. Root's
            # tar keeps the archive's modes, which are the operator checkout's (0600 under a
            # umask-077 or Git Bash checkout), but the edge and app containers read the bind
            # mounts as non-root users: normalise them. The bundle holds no secret.
            cat <<EOF
install -d -m 0755 /opt/propertyscope/app
rm -rf /opt/propertyscope/app/deployment /opt/propertyscope/app/docker-compose*.yml
printf '%s' '$(bundle_base64)' | base64 -d | tar -xzf - -C /opt/propertyscope/app --no-same-owner
chmod -R u=rwX,go=rX /opt/propertyscope/app/deployment /opt/propertyscope/app/docker-compose*.yml
chmod 0755 /opt/propertyscope/app/deployment/azure/vm/*.sh /opt/propertyscope/app/deployment/azure/compose/*
EOF
            ;;
        *)
            # Read-only actions use what the last deployment installed.
            printf '%s\n' 'test -f /opt/propertyscope/app/deployment/azure/vm/propertyscope-vm.sh || { echo "Nothing deployed yet: run deploy.sh deploy"; echo PROPERTYSCOPE_EXIT=3; exit 3; }'
            ;;
    esac
    cat <<EOF
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
    if [[ $REHEARSAL == true ]]; then
        power=$(docker inspect --format '{{.State.Running}}' "$PROPERTYSCOPE_REHEARSAL_VM" 2>/dev/null | tr -d '\r' || true)
        [[ $power == true ]] || die "the rehearsal VM container $PROPERTYSCOPE_REHEARSAL_VM is not running (dev.py cloud rehearse starts it)"
        return 0
    fi
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
    if [[ $REHEARSAL == true ]]; then
        # The same payload, run as root in the rehearsal VM; like run-command, the message is the
        # combined output and the exit status comes from the PROPERTYSCOPE_EXIT line. Like
        # run-command it runs as a file without stdin: `compose exec` inside the VM script would
        # otherwise read the rest of a payload fed on stdin. MSYS_NO_PATHCONV keeps Git Bash from
        # rewriting the VM-side path.
        log "Running '$action' on the rehearsal VM $PROPERTYSCOPE_REHEARSAL_VM (docker exec in place of az vm run-command)"
        MSYS_NO_PATHCONV=1 docker exec -i "$PROPERTYSCOPE_REHEARSAL_VM" \
            sh -c 'umask 077 && mkdir -p /var/lib/propertyscope-rehearsal/run-command && cat >/var/lib/propertyscope-rehearsal/run-command/script.sh' \
            <"$payload"
        message=$(MSYS_NO_PATHCONV=1 docker exec "$PROPERTYSCOPE_REHEARSAL_VM" \
            bash /var/lib/propertyscope-rehearsal/run-command/script.sh 2>&1 </dev/null | tr -d '\r') || true
    else
        log "Running '$action' on $VM_NAME through az vm run-command invoke"
        message=$(az_query vm run-command invoke --resource-group "$AZURE_RESOURCE_GROUP" --name "$VM_NAME" \
            --command-id RunShellScript --scripts "@$(native_path "$payload")" --query 'value[0].message' --output tsv)
    fi
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
    if [[ $DRY_RUN != true && $REHEARSAL == true ]]; then
        registry_has_image propertyscope/shared-frontend "$IMAGE_TAG" ||
            die "the rehearsal registry has no images for $IMAGE_TAG; run 'deploy.sh push' first"
    elif [[ $DRY_RUN != true ]]; then
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
    printf 'https://%s' "$PUBLIC_FQDN"
}

# What was deployed, for the smoke document: IMAGE_TAG, else the tag `push` recorded, else this
# checkout's tag; the commit from PROPERTYSCOPE_DEPLOY_SHA (the workflow), else the tag.
deployed_image_tag() {
    if [[ -z ${IMAGE_TAG:-} && -s $LOG_DIR/image-tag.txt ]]; then
        IMAGE_TAG=$(head -n 1 "$LOG_DIR/image-tag.txt" | tr -d '\r')
    fi
    image_tag
}

# The smoke test and the endpoint validation sign in with the site-wide viewer login while
# PROPERTYSCOPE_SITE_AUTH=on. The password comes from the caller's environment and reaches only
# those child processes (never a command line or a log): in GitHub Actions the production
# environment secret PROPERTYSCOPE_SITE_PASSWORD; on a laptop the operator exports it. This script
# never reads a secret value out of Key Vault itself.
require_site_password() {
    [[ $PROPERTYSCOPE_SITE_AUTH == on && -z ${PROPERTYSCOPE_SITE_PASSWORD:-} && $DRY_RUN != true ]] || return 0
    [[ $REHEARSAL != true ]] || die "the rehearsal passes PROPERTYSCOPE_SITE_PASSWORD (dev.py cloud rehearse sets it)"
    die "the site login is on (PROPERTYSCOPE_SITE_AUTH=on): set PROPERTYSCOPE_SITE_PASSWORD to the Key Vault secret $SITE_PASSWORD_SECRET (GitHub Actions: the production environment secret of the same name)"
}

# When HTTPS is limited to listed sources (AZURE_ALLOWED_HTTPS_SOURCES), admits this machine's
# public IPv4 address on 443 until the command exits, so a GitHub-hosted runner can smoke-test and
# validate the edge. Port 80 is always open. PROPERTYSCOPE_CLIENT_IP skips the address lookup.
open_https_for_this_client() {
    [[ $REHEARSAL != true && $DRY_RUN != true ]] || return 0
    local nsg sources client
    nsg=$(az_query deployment group show --resource-group "$AZURE_RESOURCE_GROUP" --name "$DEPLOYMENT_NAME" \
        --query properties.outputs.nsgName.value --output tsv 2>/dev/null || true)
    [[ -n $nsg ]] || return 0
    sources=$(az_query network nsg rule show --resource-group "$AZURE_RESOURCE_GROUP" --nsg-name "$nsg" \
        --name AllowHttpsInbound --query "[sourceAddressPrefix, join(' ', sourceAddressPrefixes)]" \
        --output tsv 2>/dev/null | tr '\t' ' ' || true)
    sources=" ${sources//None/} "
    if [[ $sources =~ [[:space:]](Internet|\*|0\.0\.0\.0/0)[[:space:]] ]]; then
        return 0
    fi
    client=${PROPERTYSCOPE_CLIENT_IP:-$(curl -fsS --max-time 10 "${PROPERTYSCOPE_IP_ECHO_URL:-https://api.ipify.org}" 2>/dev/null | tr -d '\r\n' || true)}
    [[ $client =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] ||
        die "HTTPS is limited to${sources% }; set PROPERTYSCOPE_CLIENT_IP to this machine's public IPv4 address"
    if [[ $sources == *" $client "* || $sources == *" $client/32 "* ]]; then
        return 0
    fi
    log "HTTPS is limited to${sources% }; admitting $client/32 on 443 until this command exits (NSG rule $TEMPORARY_HTTPS_RULE)"
    az network nsg rule create --resource-group "$AZURE_RESOURCE_GROUP" --nsg-name "$nsg" --name "$TEMPORARY_HTTPS_RULE" \
        --priority 120 --direction Inbound --access Allow --protocol Tcp --source-address-prefixes "$client/32" \
        --source-port-ranges '*' --destination-address-prefixes '*' --destination-port-ranges 443 \
        --description "Temporary: deploy.sh smoke or validate-endpoint; removed when the command exits" \
        --only-show-errors --output none
    # shellcheck disable=SC2064 # expand now: the locals are gone when the EXIT trap runs
    trap "az network nsg rule delete --resource-group '$AZURE_RESOURCE_GROUP' --nsg-name '$nsg' --name '$TEMPORARY_HTTPS_RULE' --only-show-errors --output none || true" EXIT
    sleep 15 # NSG rule changes take a few seconds to apply
}

cmd_smoke() {
    local output_dir="$LOG_DIR/smoke" base_url runner tag commit
    local extra=()
    while (($#)); do
        case $1 in
            --output-dir)
                output_dir=$2
                shift 2
                ;;
            --expect-ai | --insecure)
                # --insecure: only before the first certificate is issued, or for the local
                # rehearsal's internal CA.
                extra+=("$1")
                shift
                ;;
            *) die "unknown smoke option: $1" ;;
        esac
    done
    if [[ -z ${PROPERTYSCOPE_PUBLIC_URL:-} && $REHEARSAL != true ]]; then
        # In this shell, not in a $(...) subshell, so ACR_LOGIN_SERVER reaches the smoke document.
        if ! outputs_known; then
            ensure_azure_context
        fi
        load_outputs
        open_https_for_this_client
    fi
    require_site_password
    if [[ $PROPERTYSCOPE_SITE_AUTH == on ]]; then
        # Signs in with PROPERTYSCOPE_SITE_USER / PROPERTYSCOPE_SITE_PASSWORD from the environment.
        extra+=(--site-login)
    fi
    base_url=$(public_base_url)
    tag=$(deployed_image_tag)
    commit=${PROPERTYSCOPE_DEPLOY_SHA:-${PROPERTYSCOPE_GIT_SHA:-${tag%-dirty}}}
    extra+=(--image-tag "$tag")
    if [[ $commit =~ ^[0-9a-f]{40}$ ]]; then
        extra+=(--commit-sha "$commit")
    fi
    if [[ -n ${ACR_LOGIN_SERVER:-} ]]; then
        extra+=(--registry "$ACR_LOGIN_SERVER")
    fi
    # The images the VM reported running (PROPERTYSCOPE_IMAGES from the last deploy).
    if [[ -s $LOG_DIR/vm-deploy.log ]]; then
        extra+=(--vm-log "$LOG_DIR/vm-deploy.log")
    fi
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
    if [[ $which == endpoint ]]; then
        # The validator signs in with the site login to reach the pages behind it.
        require_site_password
        open_https_for_this_client
    fi
    if [[ $REHEARSAL == true ]]; then
        [[ $which == endpoint ]] ||
            die "validate-data reads Azure; the rehearsal runs its on-host half with vm-validate-data"
        # No NSG to read: the endpoint script reports it as SKIP.
        run env -u AZURE_RESOURCE_GROUP bash "$SCRIPT_DIR/validate-$which-security.sh"
        return
    fi
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
        push) cmd_push "$@" ;;
        deploy) cmd_deploy ;;
        smoke) cmd_smoke "$@" ;;
        ai) cmd_ai "$@" ;;
        status) cmd_status ;;
        logs) cmd_logs "$@" ;;
        outputs) cmd_outputs ;;
        validate-endpoint) cmd_validate endpoint ;;
        validate-data) cmd_validate data ;;
        vm-validate-data)
            # Internal: the on-host half of validate-data-security.sh.
            ensure_azure_context
            vm_environment
            vm_run validate-data
            ;;
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

# Sourcing the script (scripts/tests/test_azure_deployment.py) defines the functions only.
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    main "$@"
fi
