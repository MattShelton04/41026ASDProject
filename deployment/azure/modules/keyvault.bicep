// Secret store for every production credential (R2-B6). RBAC authorisation only (no access
// policies), soft delete with purge protection, and a firewall that admits the VM subnet through
// its service endpoint plus any explicitly listed operator addresses.

param location string

@minLength(3)
@maxLength(24)
param keyVaultName string

@description('Subnet allowed through the Key Vault firewall (service endpoint).')
param subnetId string

@description('Public operator IPv4 addresses or CIDR ranges allowed to manage secrets.')
param operatorIpRanges array = []

@allowed([
  'Allow'
  'Deny'
])
@description('Deny keeps the vault reachable only from the VM subnet and operatorIpRanges.')
param networkDefaultAction string = 'Deny'

@minValue(7)
@maxValue(90)
@description('Fixed at creation. Purge protection keeps deleted secrets recoverable for this long.')
param softDeleteRetentionInDays int = 7

param tags object = {}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: softDeleteRetentionInDays
    enablePurgeProtection: true
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: false
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: networkDefaultAction
      virtualNetworkRules: [
        {
          id: subnetId
          ignoreMissingVnetServiceEndpoint: false
        }
      ]
      ipRules: [for range in operatorIpRanges: {
        value: range
      }]
    }
  }
}

output keyVaultId string = vault.id
output keyVaultName string = vault.name
output keyVaultUri string = vault.properties.vaultUri
