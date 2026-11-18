metadata name = 'Ticker Lens'
metadata description = 'A single Python web app and keyless Foundry Decision deployment.'

@description('Region for the web app and plan.')
param location string

@description('Region supporting the selected Decision model.')
param modelLocation string

@description('Globally unique web app and Foundry name base.')
@maxLength(40)
param appName string

@description('Decision deployment name used by the application.')
param deploymentName string = 'decision'

@description('Decision model deployment SKU.')
@allowed(['GlobalStandard', 'DataZoneStandard'])
param modelSku string = 'GlobalStandard'

@description('Decision deployment capacity in model-specific units.')
@minValue(1)
param modelCapacity int = 30

@description('App Service plan SKU.')
param planSku string = 'B1'

@description('Finnhub API key supplied only to server-side settings.')
@secure()
param finnhubApiKey string

@description('Single-tenant Entra application client ID for interactive sign-in.')
param authClientId string

@description('Entra application secret for App Service sign-in.')
@secure()
param authClientSecret string

@description('Object IDs of users allowed to access the hosted demo.')
@minLength(1)
param allowedUsers array

var tags = {
  application: 'ticker-lens'
}

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: '${appName}-ai'
  location: modelLocation
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  tags: tags
  properties: {
    allowProjectManagement: true
    customSubDomainName: '${appName}-ai'
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: 'ticker-lens'
  location: modelLocation
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Ticker Lens'
    description: 'Educational financial news classification demo.'
  }
}

resource decision 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: deploymentName
  sku: {
    name: modelSku
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'Microsoft'
      name: 'Microsoft-Decision-1.1'
      version: '1'
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: '${appName}-plan'
  location: location
  kind: 'linux'
  tags: tags
  sku: { name: planSku }
  properties: { reserved: true }
}

resource web 'Microsoft.Web/sites@2024-04-01' = {
  name: appName
  location: location
  kind: 'app,linux'
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appCommandLine: 'python -m uvicorn ticker_lens.app:app --host 0.0.0.0 --port 8000'
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      healthCheckPath: '/health'
      appSettings: [
        { name: 'FINNHUB_API_KEY', value: finnhubApiKey }
        { name: 'AZURE_ENDPOINT', value: foundry.properties.endpoint }
        { name: 'DEPLOYMENT_NAME', value: decision.name }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'AUTH_CLIENT_SECRET', value: authClientSecret }
      ]
    }
  }
}

resource auth 'Microsoft.Web/sites/config@2022-09-01' = {
  parent: web
  name: 'authsettingsV2'
  properties: {
    platform: { enabled: true }
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
      excludedPaths: ['/health']
    }
    httpSettings: { requireHttps: true }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: authClientId
          clientSecretSettingName: 'AUTH_CLIENT_SECRET'
          openIdIssuer: '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [authClientId]
          defaultAuthorizationPolicy: {
            allowedPrincipals: { identities: allowedUsers }
          }
        }
      }
    }
    login: { tokenStore: { enabled: true } }
  }
}

resource inferenceRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, web.id, 'inference')
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')
    principalId: web.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

@description('Hosted application URL.')
output appUrl string = 'https://${web.properties.defaultHostName}'

@description('Web app name used for zip deployment.')
output webAppName string = web.name

@description('Foundry resource endpoint for local development.')
output azureEndpoint string = foundry.properties.endpoint

@description('Deployed Decision model name.')
output decisionDeployment string = decision.name

@description('Foundry resource ID used for local inference role assignment.')
output foundryResourceId string = foundry.id
