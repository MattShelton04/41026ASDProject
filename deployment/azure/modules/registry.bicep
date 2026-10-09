// Private image registry. Images are tagged with the Git commit SHA; nothing pulls anonymously and
// the admin user stays disabled, so every push and pull is an Entra ID (RBAC) identity.

param location string

@minLength(5)
@maxLength(50)
@description('Globally unique, alphanumeric registry name.')
param registryName string

@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param sku string = 'Basic'

param tags object = {}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  tags: tags
  sku: {
    name: sku
  }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    publicNetworkAccess: 'Enabled'
    zoneRedundancy: 'Disabled'
  }
}

output registryId string = registry.id
output registryName string = registry.name
output loginServer string = registry.properties.loginServer
