// The single Ubuntu 24.04 host (ADR-048, decision D1). It runs the existing Compose stack from ACR
// images and, only when PROPERTYSCOPE_CLOUD_AI=true, the AI tier as systemd host processes.
//
// customData and the SSH key are immutable once the VM exists. main.bicep therefore deploys this
// module only when the VM is absent (deploy.sh detects it); later releases converge the host
// through `az vm run-command` instead of re-creating it.

param location string
param vmName string

@description('16 GiB RAM or more: about 20 containers plus the optional RAG embedding model.')
param vmSize string = 'Standard_D4s_v5'

param adminUsername string = 'propertyscope'

@description('Required by Azure for Linux VMs. No NSG rule admits SSH; the private key need not be kept.')
param adminSshPublicKey string

param subnetId string
param publicIpId string

@minValue(64)
@maxValue(1024)
param osDiskSizeGB int = 128

@allowed([
  'Premium_LRS'
  'StandardSSD_LRS'
])
param osDiskType string = 'Premium_LRS'

@description('Host-based encryption of temp/cache disks and data in transit to storage. Requires the subscription feature Microsoft.Compute/EncryptionAtHost.')
param enableEncryptionAtHost bool = true

param tags object = {}

resource nic 'Microsoft.Network/networkInterfaces@2024-05-01' = {
  name: '${vmName}-nic'
  location: location
  tags: tags
  properties: {
    enableAcceleratedNetworking: true
    ipConfigurations: [
      {
        name: 'primary'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: {
            id: subnetId
          }
          publicIPAddress: {
            id: publicIpId
          }
        }
      }
    ]
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
  name: vmName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    hardwareProfile: {
      vmSize: vmSize
    }
    securityProfile: {
      encryptionAtHost: enableEncryptionAtHost
      securityType: 'TrustedLaunch'
      uefiSettings: {
        secureBootEnabled: true
        vTpmEnabled: true
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: 'latest'
      }
      osDisk: {
        name: '${vmName}-osdisk'
        createOption: 'FromImage'
        caching: 'ReadWrite'
        diskSizeGB: osDiskSizeGB
        deleteOption: 'Delete'
        managedDisk: {
          // Managed disks are always encrypted at rest with platform-managed keys (SSE).
          storageAccountType: osDiskType
        }
      }
    }
    osProfile: {
      computerName: vmName
      adminUsername: adminUsername
      customData: base64(loadTextContent('../cloud-init.yaml'))
      linuxConfiguration: {
        disablePasswordAuthentication: true
        provisionVMAgent: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: adminSshPublicKey
            }
          ]
        }
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: nic.id
          properties: {
            deleteOption: 'Delete'
          }
        }
      ]
    }
    diagnosticsProfile: {
      bootDiagnostics: {
        // Managed storage: enables the serial console as a break-glass path without SSH.
        enabled: true
      }
    }
  }
}

output vmId string = vm.id
output vmName string = vm.name
output principalId string = vm.identity.principalId
