// Daily deallocation so an idle demo VM stops costing compute. deploy.sh starts the VM again
// before every deployment, so a scheduled shutdown never breaks a later release.

param location string
param vmName string

@description('Daily shutdown time as HHmm (24 hour clock).')
param time string

param timeZoneId string = 'AUS Eastern Standard Time'

param tags object = {}

resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' existing = {
  name: vmName
}

resource schedule 'Microsoft.DevTestLab/schedules@2018-09-15' = {
  name: 'shutdown-computevm-${vmName}'
  location: location
  tags: tags
  properties: {
    status: 'Enabled'
    taskType: 'ComputeVmShutdownTask'
    dailyRecurrence: {
      time: time
    }
    timeZoneId: timeZoneId
    targetResourceId: vm.id
    notificationSettings: {
      status: 'Disabled'
    }
  }
}
