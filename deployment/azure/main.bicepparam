// Production parameters. Values that differ per subscription come from environment variables, so
// the same file serves a laptop (deployment/azure/.env.azure) and GitHub Actions (repository
// variables). Nothing here is secret. See deployment/azure/README.md for every variable.
using './main.bicep'

param location = readEnvironmentVariable('AZURE_LOCATION', 'australiaeast')
param namePrefix = readEnvironmentVariable('AZURE_NAME_PREFIX', 'propertyscope')
param environmentName = 'prod'
param dnsLabel = readEnvironmentVariable('AZURE_DNS_LABEL', 'propertyscope-nsw-g20')
param vmSize = readEnvironmentVariable('AZURE_VM_SIZE', 'Standard_D4s_v5')
param adminSshPublicKey = readEnvironmentVariable('AZURE_VM_SSH_PUBLIC_KEY', '')
param deployVirtualMachine = bool(readEnvironmentVariable('AZURE_DEPLOY_VM', 'true'))
param enableEncryptionAtHost = bool(readEnvironmentVariable('AZURE_ENCRYPTION_AT_HOST', 'true'))
param autoShutdownTime = readEnvironmentVariable('AZURE_AUTO_SHUTDOWN_TIME', '2330')
param operatorIpRanges = empty(readEnvironmentVariable('AZURE_OPERATOR_IP_RANGES', '')) ? [] : split(readEnvironmentVariable('AZURE_OPERATOR_IP_RANGES', ''), ',')
param keyVaultNetworkDefaultAction = readEnvironmentVariable('AZURE_KEY_VAULT_DEFAULT_ACTION', 'Deny')
param deployerPrincipalId = readEnvironmentVariable('AZURE_DEPLOYER_PRINCIPAL_ID', '')
param secretOfficerPrincipalIds = empty(readEnvironmentVariable('AZURE_SECRET_OFFICER_IDS', '')) ? [] : split(readEnvironmentVariable('AZURE_SECRET_OFFICER_IDS', ''), ',')
param deployBudget = bool(readEnvironmentVariable('AZURE_DEPLOY_BUDGET', 'true'))
param monthlyBudget = int(readEnvironmentVariable('AZURE_MONTHLY_BUDGET', '100'))
param budgetStartDate = readEnvironmentVariable('AZURE_BUDGET_START_DATE', '2026-10-01')
param budgetContactEmails = empty(readEnvironmentVariable('AZURE_BUDGET_EMAILS', '')) ? [] : split(readEnvironmentVariable('AZURE_BUDGET_EMAILS', ''), ',')
param tags = {
  course: '41026-advanced-software-development'
  team: 'group-20'
}
