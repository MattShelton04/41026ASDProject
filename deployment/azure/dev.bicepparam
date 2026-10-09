// Example low-cost rehearsal environment (separate resource group, e.g. rg-propertyscope-dev).
// Use it to rehearse provisioning before production: AZURE_PARAMETERS_FILE=deployment/azure/dev.bicepparam
// It keeps every security control except encryption at host, so it also works on a subscription
// where the EncryptionAtHost feature is not registered yet.
using './main.bicep'

param location = readEnvironmentVariable('AZURE_LOCATION', 'australiaeast')
param namePrefix = 'propertyscope'
param environmentName = 'dev'
param vmSize = readEnvironmentVariable('AZURE_VM_SIZE', 'Standard_D4s_v5')
param adminSshPublicKey = readEnvironmentVariable('AZURE_VM_SSH_PUBLIC_KEY', '')
param deployVirtualMachine = bool(readEnvironmentVariable('AZURE_DEPLOY_VM', 'true'))
param enableEncryptionAtHost = false
param osDiskSizeGB = 64
param autoShutdownTime = '1900'
param operatorIpRanges = empty(readEnvironmentVariable('AZURE_OPERATOR_IP_RANGES', '')) ? [] : split(readEnvironmentVariable('AZURE_OPERATOR_IP_RANGES', ''), ',')
param secretOfficerPrincipalIds = empty(readEnvironmentVariable('AZURE_SECRET_OFFICER_IDS', '')) ? [] : split(readEnvironmentVariable('AZURE_SECRET_OFFICER_IDS', ''), ',')
param deployerPrincipalId = readEnvironmentVariable('AZURE_DEPLOYER_PRINCIPAL_ID', '')
param deployBudget = false
param tags = {
  course: '41026-advanced-software-development'
  team: 'group-20'
  purpose: 'rehearsal'
}
