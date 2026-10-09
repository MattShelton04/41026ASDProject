// Least-privilege role assignments. The VM's system-assigned identity may only pull images and
// read secrets; it cannot push images, write secrets or change any resource.

@description('Object ID of the VM system-assigned managed identity.')
param vmPrincipalId string

param registryName string
param keyVaultName string

@description('Optional deployer service principal (GitHub OIDC app) granted AcrPush.')
param deployerPrincipalId string = ''

@description('Optional operators (user or group object IDs) granted Key Vault Secrets Officer.')
param secretOfficerPrincipalIds array = []

@allowed([
  'User'
  'Group'
  'ServicePrincipal'
])
param secretOfficerPrincipalType string = 'User'

var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  acrPush: '8311e382-0749-4cb8-b61a-304f252e45ec'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  keyVaultSecretsOfficer: 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource vmAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, vmPrincipalId, roles.acrPull)
  scope: registry
  properties: {
    principalId: vmPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    description: 'PropertyScope VM pulls release images by commit SHA.'
  }
}

resource vmSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, vmPrincipalId, roles.keyVaultSecretsUser)
  scope: vault
  properties: {
    principalId: vmPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
    description: 'PropertyScope VM renders runtime secrets with its managed identity.'
  }
}

resource deployerAcrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(registry.id, deployerPrincipalId, roles.acrPush)
  scope: registry
  properties: {
    principalId: deployerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPush)
    description: 'GitHub Actions (OIDC) pushes release images.'
  }
}

resource officers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in secretOfficerPrincipalIds: {
  name: guid(vault.id, principalId, roles.keyVaultSecretsOfficer)
  scope: vault
  properties: {
    principalId: principalId
    principalType: secretOfficerPrincipalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsOfficer)
    description: 'PropertyScope operator manages production secrets.'
  }
}]
