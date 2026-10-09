// PropertyScope NSW - Release 2 Azure environment (ADR-048).
//
// Resource-group scope. deploy.sh creates the resource group first (`az group create`), then runs
// this template. Everything here is idempotent: re-running converges the same resources.
//
//   Internet :443/:80 -> Standard public IP (DNS label) -> NSG (80/443 only) -> Ubuntu 24.04 VM
//   VM managed identity -> AcrPull on ACR, Key Vault Secrets User on Key Vault
//   VM: Caddy TLS -> nginx edge -> Compose services; databases on internal networks only
//   VM: systemd AI units (ai-mode, mcp, rag, multi-agent), off unless PROPERTYSCOPE_CLOUD_AI=true

targetScope = 'resourceGroup'

@description('Azure region. australiaeast is the team default.')
param location string = resourceGroup().location

@minLength(3)
@maxLength(16)
@description('Lowercase prefix for resource names.')
param namePrefix string = 'propertyscope'

@allowed([
  'prod'
  'dev'
  'test'
])
param environmentName string = 'prod'

@description('Public DNS label (<label>.<region>.cloudapp.azure.com). Defaults to a stable unique label.')
param dnsLabel string = '${namePrefix}-${environmentName}-${take(uniqueString(resourceGroup().id), 6)}'

@description('VM size; 16 GiB RAM or more (Standard_D4s_v5 = 4 vCPU / 16 GiB).')
param vmSize string = 'Standard_D4s_v5'

param adminUsername string = 'propertyscope'

@description('SSH public key Azure requires for a Linux VM. No NSG rule admits SSH and sshd is disabled; deploy.sh supplies a throwaway key when none is configured.')
param adminSshPublicKey string

@description('False when the VM already exists: its customData and SSH key are immutable, so later releases converge it through run-command.')
param deployVirtualMachine bool = true

@minValue(64)
@maxValue(1024)
param osDiskSizeGB int = 128

@description('Requires `az feature register --namespace Microsoft.Compute --name EncryptionAtHost` once per subscription.')
param enableEncryptionAtHost bool = true

@description('Daily deallocation time as HHmm, or empty to keep the VM running.')
param autoShutdownTime string = '2330'

param autoShutdownTimeZone string = 'AUS Eastern Standard Time'

@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param acrSku string = 'Basic'

@description('Public operator IPv4 addresses/CIDRs allowed through the Key Vault firewall (for secret setup).')
param operatorIpRanges array = []

@allowed([
  'Allow'
  'Deny'
])
param keyVaultNetworkDefaultAction string = 'Deny'

@description('Object ID of the GitHub OIDC service principal; granted AcrPush when set.')
param deployerPrincipalId string = ''

@description('User/group object IDs granted Key Vault Secrets Officer (to create the runtime secrets).')
param secretOfficerPrincipalIds array = []

@allowed([
  'User'
  'Group'
  'ServicePrincipal'
])
param secretOfficerPrincipalType string = 'User'

@description('Create a monthly consumption budget on the resource group.')
param deployBudget bool = true

@minValue(1)
param monthlyBudget int = 100

@description('First day of the budget month (yyyy-MM-01). Keep fixed after the first deployment.')
param budgetStartDate string = '2026-10-01'

@description('Budget alert recipients.')
param budgetContactEmails array = []

param tags object = {}

var baseName = '${namePrefix}-${environmentName}'
var suffix = uniqueString(resourceGroup().id)
var allTags = union(
  {
    application: 'propertyscope-nsw'
    environment: environmentName
    'managed-by': 'bicep'
    release: 'release-2'
  },
  tags
)
var vmName = '${baseName}-vm'
var registryName = take(toLower(replace('${namePrefix}${environmentName}${suffix}', '-', '')), 50)
var keyVaultName = take('${take(namePrefix, 8)}-kv-${suffix}', 24)

module network 'modules/network.bicep' = {
  name: 'propertyscope-network'
  params: {
    location: location
    namePrefix: baseName
    dnsLabel: dnsLabel
    tags: allTags
  }
}

module registry 'modules/registry.bicep' = {
  name: 'propertyscope-registry'
  params: {
    location: location
    registryName: registryName
    sku: acrSku
    tags: allTags
  }
}

module keyVault 'modules/keyvault.bicep' = {
  name: 'propertyscope-keyvault'
  params: {
    location: location
    keyVaultName: keyVaultName
    subnetId: network.outputs.subnetId
    operatorIpRanges: operatorIpRanges
    networkDefaultAction: keyVaultNetworkDefaultAction
    tags: allTags
  }
}

module virtualMachine 'modules/vm.bicep' = if (deployVirtualMachine) {
  name: 'propertyscope-vm'
  params: {
    location: location
    vmName: vmName
    vmSize: vmSize
    adminUsername: adminUsername
    adminSshPublicKey: adminSshPublicKey
    subnetId: network.outputs.subnetId
    publicIpId: network.outputs.publicIpId
    osDiskSizeGB: osDiskSizeGB
    enableEncryptionAtHost: enableEncryptionAtHost
    tags: allTags
  }
}

resource existingVm 'Microsoft.Compute/virtualMachines@2024-07-01' existing = {
  name: vmName
}

// ARM evaluates only the selected branch of a conditional, so the existing-VM reference is never
// read while the VM is being created in the same deployment.
var vmPrincipalId = deployVirtualMachine ? virtualMachine.outputs.principalId : existingVm.identity.principalId

module access 'modules/access.bicep' = {
  name: 'propertyscope-access'
  params: {
    vmPrincipalId: vmPrincipalId
    registryName: registry.outputs.registryName
    keyVaultName: keyVault.outputs.keyVaultName
    deployerPrincipalId: deployerPrincipalId
    secretOfficerPrincipalIds: secretOfficerPrincipalIds
    secretOfficerPrincipalType: secretOfficerPrincipalType
  }
}

module shutdown 'modules/shutdown.bicep' = if (!empty(autoShutdownTime)) {
  name: 'propertyscope-shutdown'
  params: {
    location: location
    vmName: vmName
    time: autoShutdownTime
    timeZoneId: autoShutdownTimeZone
    tags: allTags
  }
  dependsOn: [
    virtualMachine
  ]
}

module budget 'modules/budget.bicep' = if (deployBudget && !empty(budgetContactEmails)) {
  name: 'propertyscope-budget'
  params: {
    budgetName: '${baseName}-monthly'
    amount: monthlyBudget
    startDate: budgetStartDate
    contactEmails: budgetContactEmails
  }
}

output resourceGroupName string = resourceGroup().name
output location string = location
output fqdn string = network.outputs.fqdn
output publicIpAddress string = network.outputs.publicIpAddress
output publicUrl string = 'https://${network.outputs.fqdn}'
output acrName string = registry.outputs.registryName
output acrLoginServer string = registry.outputs.loginServer
output vmName string = vmName
output vmPrincipalId string = vmPrincipalId
output keyVaultName string = keyVault.outputs.keyVaultName
output keyVaultUri string = keyVault.outputs.keyVaultUri
output nsgName string = network.outputs.nsgName
