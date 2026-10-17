// Example low-cost rehearsal environment (separate resource group, e.g. rg-propertyscope-dev).
// Use it to rehearse provisioning before production: AZURE_PARAMETERS_FILE=deployment/azure/dev.bicepparam
// It keeps every security control except encryption at host, so it also works on a subscription
// where the EncryptionAtHost feature is not registered yet.
// Empty environment values fall back to the defaults, as in main.bicepparam. The DNS label is the
// stable unique default from main.bicep (propertyscope-dev-<6 characters>).
using './main.bicep'

var locationSetting = readEnvironmentVariable('AZURE_LOCATION', 'australiaeast')
var vmSizeSetting = readEnvironmentVariable('AZURE_VM_SIZE', 'Standard_D4s_v5')
var operatorIpRangesSetting = readEnvironmentVariable('AZURE_OPERATOR_IP_RANGES', '')
var httpsSourcesSetting = readEnvironmentVariable('AZURE_ALLOWED_HTTPS_SOURCES', '')
var secretOfficerIdsSetting = readEnvironmentVariable('AZURE_SECRET_OFFICER_IDS', '')

param location = empty(locationSetting) ? 'australiaeast' : locationSetting
param namePrefix = 'propertyscope'
param environmentName = 'dev'
param vmSize = empty(vmSizeSetting) ? 'Standard_D4s_v5' : vmSizeSetting
param adminSshPublicKey = readEnvironmentVariable('AZURE_VM_SSH_PUBLIC_KEY', '')
param deployVirtualMachine = toLower(readEnvironmentVariable('AZURE_DEPLOY_VM', 'true')) != 'false'
param enableEncryptionAtHost = false
param osDiskSizeGB = 64
param autoShutdownTime = '1900'
param operatorIpRanges = empty(operatorIpRangesSetting) ? [] : split(operatorIpRangesSetting, ',')
// Empty: HTTPS open to the internet. A comma list (e.g. 203.0.113.7/32,198.51.100.0/24) limits 443 only.
param allowedHttpsSourcePrefixes = empty(httpsSourcesSetting) ? ['Internet'] : split(httpsSourcesSetting, ',')
param secretOfficerPrincipalIds = empty(secretOfficerIdsSetting) ? [] : split(secretOfficerIdsSetting, ',')
param keyVaultNameSeed = readEnvironmentVariable('AZURE_KEY_VAULT_NAME_SEED', '')
param deployerPrincipalId = readEnvironmentVariable('AZURE_DEPLOYER_PRINCIPAL_ID', '')
param deployBudget = false
param tags = {
  course: '41026-advanced-software-development'
  team: 'group-20'
  purpose: 'rehearsal'
}
