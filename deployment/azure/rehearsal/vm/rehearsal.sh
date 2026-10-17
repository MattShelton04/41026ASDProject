# shellcheck shell=bash
# Local rehearsal only (`uv run scripts/dev.py cloud rehearse`). NEVER installed on an Azure VM.
#
# The rehearsal VM container (deployment/azure/rehearsal/vm/Dockerfile) installs this file as
# /etc/propertyscope/rehearsal.sh. deployment/azure/vm/propertyscope-vm.sh sources it after
# defining its functions, so every step of the real VM script runs unchanged except the three
# Azure-only ones, which have no local equivalent:
#
#   imds_token        no Instance Metadata Service: there is no managed identity to ask
#   kv_get            the "Key Vault" is a read-only directory of throwaway values that
#                     dev.py cloud rehearse generated (mounted at $REHEARSAL_KEY_VAULT)
#   acr_login/logout  the rehearsal registry (registry:2) is anonymous: no token exchange
#
# verify_deployment additionally trusts Caddy's internal CA, because PROPERTYSCOPE_PUBLIC_HOST is
# localhost and Caddy issues it a certificate from its own CA instead of Let's Encrypt.

REHEARSAL_KEY_VAULT=/var/lib/propertyscope-rehearsal/key-vault
REHEARSAL_EDGE_CA=/data/caddy/pki/authorities/local/root.crt

imds_token() {
    printf 'rehearsal-without-imds'
}

kv_get() {
    local name=$1 optional=${2:-} file
    [[ $name =~ ^[a-z0-9-]{1,127}$ ]] || die "invalid secret name: $name"
    file=$REHEARSAL_KEY_VAULT/$name
    if [[ -s $file ]]; then
        cat "$file"
        return 0
    fi
    if [[ $optional == optional ]]; then
        return 3
    fi
    die "the rehearsal Key Vault has no secret '$name' (dev.py cloud rehearse generates them)"
}

acr_login() {
    log "Rehearsal: ${ACR_LOGIN_SERVER} is an anonymous local registry (no managed-identity token exchange)"
}

acr_logout() {
    :
}

# Keep the Azure implementation and wrap it.
eval "azure_verify_deployment() $(declare -f verify_deployment | sed '1d')"

verify_deployment() {
    local ca=$STATE_DIR/rehearsal-edge-root.crt _attempt
    for _attempt in $(seq 1 24); do
        if compose exec -T shared-edge-proxy cat "$REHEARSAL_EDGE_CA" >"$ca.tmp" 2>/dev/null && [[ -s $ca.tmp ]]; then
            mv -f "$ca.tmp" "$ca"
            break
        fi
        sleep 5
    done
    rm -f "$ca.tmp"
    if [[ -s $ca ]]; then
        log "Rehearsal: trusting Caddy's internal CA for ${PROPERTYSCOPE_PUBLIC_HOST} (Azure gets a Let's Encrypt certificate)"
        (
            export CURL_CA_BUNDLE=$ca
            azure_verify_deployment
        )
    else
        log "Rehearsal: Caddy's internal CA is not available yet; the HTTPS check will not trust the edge"
        azure_verify_deployment
    fi
}
