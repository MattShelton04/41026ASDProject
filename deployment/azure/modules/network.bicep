// Network edge for the single PropertyScope VM (ADR-048).
//
// Only HTTP (ACME challenge + redirect) and HTTPS reach the VM from the internet. There is no SSH
// or database rule: operators use `az vm run-command`, and every database stays on internal
// Compose networks inside the VM.

@description('Azure region for every network resource.')
param location string

@description('Resource name prefix, for example propertyscope-prod.')
param namePrefix string

@description('Public DNS label; the FQDN becomes <label>.<region>.cloudapp.azure.com.')
param dnsLabel string

@description('Virtual network address space.')
param addressPrefix string = '10.42.0.0/16'

@description('Application subnet address range.')
param subnetPrefix string = '10.42.1.0/24'

@description('Source address prefixes allowed to reach 80/443. Keep Internet for a public demo.')
param allowedHttpSourcePrefixes array = [
  'Internet'
]

param tags object = {}

resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${namePrefix}-nsg'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowHttpsInbound'
        properties: {
          description: 'Caddy terminates TLS for the PropertyScope edge.'
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefixes: allowedHttpSourcePrefixes
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '443'
        }
      }
      {
        name: 'AllowHttpInbound'
        properties: {
          description: 'ACME HTTP-01 challenges and the permanent HTTP to HTTPS redirect only.'
          priority: 110
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefixes: allowedHttpSourcePrefixes
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '80'
        }
      }
      {
        name: 'DenyAllOtherInternetInbound'
        properties: {
          description: 'Explicit: no SSH, database, AI or management port is reachable from the internet.'
          priority: 4000
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${namePrefix}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        addressPrefix
      ]
    }
    subnets: [
      {
        name: 'app'
        properties: {
          addressPrefix: subnetPrefix
          networkSecurityGroup: {
            id: nsg.id
          }
          // Lets the Key Vault firewall admit only this subnet (plus listed operator IPs).
          serviceEndpoints: [
            {
              service: 'Microsoft.KeyVault'
            }
          ]
          privateEndpointNetworkPolicies: 'Enabled'
          defaultOutboundAccess: false
        }
      }
    ]
  }
}

resource publicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: '${namePrefix}-pip'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
    idleTimeoutInMinutes: 10
    dnsSettings: {
      domainNameLabel: dnsLabel
    }
  }
}

output subnetId string = vnet.properties.subnets[0].id
output publicIpId string = publicIp.id
output publicIpAddress string = publicIp.properties.ipAddress
output fqdn string = publicIp.properties.dnsSettings.fqdn
output nsgName string = nsg.name
output vnetName string = vnet.name
