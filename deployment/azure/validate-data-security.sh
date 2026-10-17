#!/usr/bin/env bash
# Data-security validation for the Azure deployment (bonus R2-B6, ADR-048).
#
# Control-plane part (read-only az queries): Key Vault RBAC, soft delete, purge protection and
# firewall; ACR admin user and anonymous pull disabled; the VM's system-assigned identity holds
# only AcrPull and Key Vault Secrets User; encryption at host and managed-disk encryption; the OS
# disk cannot be exported; no inbound SSH or database rule; the GitHub deployer (app registration
# or user-assigned managed identity) uses a federated credential, not a secret.
# On-host part (through `az vm run-command`, see propertyscope-vm.sh validate-data): secret files
# are root-only, no secret value appears in any container environment (`docker inspect`) or image
# history, data networks are internal, databases publish no port and sit off the shared network,
# nothing but 80/443 listens publicly, sshd is stopped, no registry credential is stored and no
# container can reach the instance metadata service (IMDS).
#
# Usage: deploy.sh validate-data
# Requires AZURE_RESOURCE_GROUP, ACR_NAME, VM_NAME, KEY_VAULT_NAME (deploy.sh exports them).
# Optional: AZURE_CLIENT_ID (checks the GitHub federated credential), LOG_DIR.
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
: "${AZURE_RESOURCE_GROUP:?}" "${ACR_NAME:?}" "${VM_NAME:?}" "${KEY_VAULT_NAME:?}"
OUTPUT_DIR=${LOG_DIR:-.}
REPORT="$OUTPUT_DIR/data-security.txt"
FAILURES=0
mkdir -p "$OUTPUT_DIR"
: >"$REPORT"

result() {
    local verdict=$1
    shift
    printf '%s %s\n' "$verdict" "$*" | tee -a "$REPORT"
    if [[ $verdict == FAIL ]]; then
        FAILURES=$((FAILURES + 1))
    fi
}

expect() {
    local description=$1 actual=$2 wanted=$3
    if [[ $actual == "$wanted" ]]; then
        result PASS "$description ($actual)"
    else
        result FAIL "$description (expected $wanted, got ${actual:-nothing})"
    fi
}

# Git Bash (MSYS) would rewrite the /subscriptions/... resource IDs passed to az (disk show --ids)
# into Windows paths; this is the same guard as deploy.sh's az().
az() { MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' command az "$@"; }

query() {
    az "$@" --only-show-errors --output tsv 2>/dev/null | tr -d '\r'
}

echo "Data security validation for $AZURE_RESOURCE_GROUP at $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$REPORT"

# --- Key Vault -------------------------------------------------------------------------------
expect "Key Vault uses RBAC authorisation (no access policies)" \
    "$(query keyvault show --name "$KEY_VAULT_NAME" --query properties.enableRbacAuthorization)" true
expect "Key Vault soft delete is enabled" \
    "$(query keyvault show --name "$KEY_VAULT_NAME" --query properties.enableSoftDelete)" true
expect "Key Vault purge protection is enabled" \
    "$(query keyvault show --name "$KEY_VAULT_NAME" --query properties.enablePurgeProtection)" true
expect "Key Vault firewall denies by default" \
    "$(query keyvault show --name "$KEY_VAULT_NAME" --query properties.networkAcls.defaultAction)" Deny

# --- Container registry ----------------------------------------------------------------------
expect "ACR admin user is disabled" "$(query acr show --name "$ACR_NAME" --query adminUserEnabled)" false
expect "ACR anonymous pull is disabled" "$(query acr show --name "$ACR_NAME" --query anonymousPullEnabled)" false

# --- VM identity, disks and encryption -------------------------------------------------------
expect "VM uses a system-assigned managed identity" \
    "$(query vm show --resource-group "$AZURE_RESOURCE_GROUP" --name "$VM_NAME" --query identity.type)" SystemAssigned
principal=$(query vm show --resource-group "$AZURE_RESOURCE_GROUP" --name "$VM_NAME" --query identity.principalId)
roles=$(query role assignment list --assignee "$principal" --all --query "[].roleDefinitionName" | sort | tr '\n' ',')
expect "VM identity holds only AcrPull and Key Vault Secrets User" "${roles%,}" "AcrPull,Key Vault Secrets User"
at_host=$(query vm show --resource-group "$AZURE_RESOURCE_GROUP" --name "$VM_NAME" --query securityProfile.encryptionAtHost)
if [[ $at_host == true ]]; then
    result PASS "encryption at host is enabled (temp disk, caches and host-to-storage traffic)"
else
    result FAIL "encryption at host is disabled (AZURE_ENCRYPTION_AT_HOST=false or feature not registered)"
fi
disk=$(query vm show --resource-group "$AZURE_RESOURCE_GROUP" --name "$VM_NAME" --query storageProfile.osDisk.managedDisk.id)
# One call for both values; az prints a list one value per line (2.89+) or tab-separated.
read -r disk_encryption disk_access < <(query disk show --ids "$disk" \
    --query "[encryption.type, networkAccessPolicy]" | tr '\n' ' ')
expect "OS disk is encrypted at rest" "${disk_encryption:-}" EncryptionAtRestWithPlatformKey
# Without this, anyone with Contributor can export the disk (secrets and databases) through a SAS.
expect "OS disk cannot be exported (network access policy)" "${disk_access:-}" DenyAll
expect "Trusted Launch (secure boot + vTPM) is enabled" \
    "$(query vm show --resource-group "$AZURE_RESOURCE_GROUP" --name "$VM_NAME" --query securityProfile.securityType)" TrustedLaunch

# --- Network exposure of data ----------------------------------------------------------------
exposed=$(query network nsg list --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "[].securityRules[?direction=='Inbound' && access=='Allow' && (destinationPortRange=='22' || destinationPortRange=='5432' || destinationPortRange=='*')].name | []")
expect "no NSG rule admits SSH, PostgreSQL or all ports" "${exposed:-none}" none

# --- Deployment credentials ------------------------------------------------------------------
if [[ -n ${AZURE_CLIENT_ID:-} ]]; then
    # The deployer is an app registration or, where the tenant blocks those, a user-assigned
    # managed identity in the resource group (deployment/azure/README.md, step 3).
    identity=$(query identity list --resource-group "$AZURE_RESOURCE_GROUP" \
        --query "[?clientId=='$AZURE_CLIENT_ID'].name | [0]")
    if [[ -n $identity ]]; then
        subjects=$(query identity federated-credential list --resource-group "$AZURE_RESOURCE_GROUP" \
            --identity-name "$identity" --query "[].subject" | tr '\n' ' ')
        kind="managed identity $identity"
        secrets=0 # a managed identity cannot hold a client secret
    else
        subjects=$(query ad app federated-credential list --id "$AZURE_CLIENT_ID" --query "[].subject" | tr '\n' ' ')
        kind="app registration"
        secrets=$(query ad app credential list --id "$AZURE_CLIENT_ID" --query "length(@)")
    fi
    if [[ $subjects == *environment:production* ]]; then
        result PASS "GitHub Actions deploys through OIDC ($kind, federated subject: ${subjects% })"
    else
        result FAIL "no federated credential for the production environment on $AZURE_CLIENT_ID ($kind)"
    fi
    expect "the deployer has no client secrets ($kind)" "${secrets:-0}" 0
else
    result SKIP "GitHub OIDC federated credential (set AZURE_CLIENT_ID)"
fi

# --- On-host checks --------------------------------------------------------------------------
if bash "$SCRIPT_DIR/deploy.sh" vm-validate-data >"$OUTPUT_DIR/data-security-vm.txt" 2>&1; then
    result PASS "on-host checks passed (see data-security-vm.txt)"
else
    result FAIL "on-host checks failed (see data-security-vm.txt)"
fi
grep -E '^(PASS|FAIL|SKIP) ' "$OUTPUT_DIR/data-security-vm.txt" | sed 's/^/  vm: /' | tee -a "$REPORT"

echo "DATA_SECURITY_FAILURES=${FAILURES}" | tee -a "$REPORT"
[[ $FAILURES -eq 0 ]]
