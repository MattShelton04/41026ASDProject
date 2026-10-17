// Production parameters. Values that differ per subscription come from environment variables, so
// the same file serves a laptop (deployment/azure/.env.azure) and GitHub Actions (repository
// variables). Nothing here is secret. See deployment/azure/README.md for every variable.
//
// readEnvironmentVariable() uses its default only when a variable is UNSET. GitHub Actions passes
// an unset repository variable as an empty string, and .env.azure may leave a value blank, so every
// setting below treats empty as "use the default" too. The one exception is
// AZURE_AUTO_SHUTDOWN_TIME, where an explicit empty value or `off` means "no auto-shutdown
// schedule". GitHub Actions can only pass `off`. Use it in a region without
// Microsoft.DevTestLab/schedules (newzealandnorth); .github/workflows/cloud-auto-deallocate.yml
// then deallocates the VM nightly instead.
using './main.bicep'

var locationSetting = readEnvironmentVariable('AZURE_LOCATION', 'australiaeast')
var namePrefixSetting = readEnvironmentVariable('AZURE_NAME_PREFIX', 'propertyscope')
var dnsLabelSetting = readEnvironmentVariable('AZURE_DNS_LABEL', 'propertyscope-nsw-g20')
var vmSizeSetting = readEnvironmentVariable('AZURE_VM_SIZE', 'Standard_D4s_v5')
var deployVmSetting = readEnvironmentVariable('AZURE_DEPLOY_VM', 'true')
var encryptionAtHostSetting = readEnvironmentVariable('AZURE_ENCRYPTION_AT_HOST', 'true')
var keyVaultDefaultActionSetting = readEnvironmentVariable('AZURE_KEY_VAULT_DEFAULT_ACTION', 'Deny')
var deployBudgetSetting = readEnvironmentVariable('AZURE_DEPLOY_BUDGET', 'true')
var monthlyBudgetSetting = readEnvironmentVariable('AZURE_MONTHLY_BUDGET', '100')
var budgetStartDateSetting = readEnvironmentVariable('AZURE_BUDGET_START_DATE', '2026-10-01')
var operatorIpRangesSetting = readEnvironmentVariable('AZURE_OPERATOR_IP_RANGES', '')
var httpsSourcesSetting = readEnvironmentVariable('AZURE_ALLOWED_HTTPS_SOURCES', '')
var secretOfficerIdsSetting = readEnvironmentVariable('AZURE_SECRET_OFFICER_IDS', '')
var budgetEmailsSetting = readEnvironmentVariable('AZURE_BUDGET_EMAILS', '')
var autoShutdownSetting = readEnvironmentVariable('AZURE_AUTO_SHUTDOWN_TIME', '2330')

param location = empty(locationSetting) ? 'australiaeast' : locationSetting
param namePrefix = empty(namePrefixSetting) ? 'propertyscope' : namePrefixSetting
param environmentName = 'prod'
// Never empty: an empty DNS label would fail the public IP (main.bicep also guards this).
param dnsLabel = empty(dnsLabelSetting) ? 'propertyscope-nsw-g20' : dnsLabelSetting
param vmSize = empty(vmSizeSetting) ? 'Standard_D4s_v5' : vmSizeSetting
param adminSshPublicKey = readEnvironmentVariable('AZURE_VM_SSH_PUBLIC_KEY', '')
param deployVirtualMachine = toLower(deployVmSetting) != 'false'
param enableEncryptionAtHost = toLower(encryptionAtHostSetting) != 'false'
param autoShutdownTime = toLower(autoShutdownSetting) == 'off' ? '' : autoShutdownSetting
param operatorIpRanges = empty(operatorIpRangesSetting) ? [] : split(operatorIpRangesSetting, ',')
// Empty: HTTPS open to the internet. A comma list (e.g. 203.0.113.7/32,198.51.100.0/24) limits 443 only.
param allowedHttpsSourcePrefixes = empty(httpsSourcesSetting) ? ['Internet'] : split(httpsSourcesSetting, ',')
param keyVaultNetworkDefaultAction = empty(keyVaultDefaultActionSetting) ? 'Deny' : keyVaultDefaultActionSetting
param keyVaultNameSeed = readEnvironmentVariable('AZURE_KEY_VAULT_NAME_SEED', '')
param deployerPrincipalId = readEnvironmentVariable('AZURE_DEPLOYER_PRINCIPAL_ID', '')
param secretOfficerPrincipalIds = empty(secretOfficerIdsSetting) ? [] : split(secretOfficerIdsSetting, ',')
param deployBudget = toLower(deployBudgetSetting) != 'false'
param monthlyBudget = int(empty(monthlyBudgetSetting) ? '100' : monthlyBudgetSetting)
param budgetStartDate = empty(budgetStartDateSetting) ? '2026-10-01' : budgetStartDateSetting
param budgetContactEmails = empty(budgetEmailsSetting) ? [] : split(budgetEmailsSetting, ',')
param tags = {
  course: '41026-advanced-software-development'
  team: 'group-20'
}
