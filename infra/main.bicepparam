using './main.bicep'

param location = readEnvironmentVariable('LOCATION')
param modelLocation = readEnvironmentVariable('MODEL_LOCATION')
param appName = readEnvironmentVariable('APP_NAME')
param deploymentName = readEnvironmentVariable('DEPLOYMENT_NAME')
param modelSku = readEnvironmentVariable('MODEL_SKU')
param modelCapacity = int(readEnvironmentVariable('MODEL_CAPACITY'))
param planSku = readEnvironmentVariable('PLAN_SKU')
param finnhubApiKey = readEnvironmentVariable('FINNHUB_API_KEY')
param authClientId = readEnvironmentVariable('AUTH_CLIENT_ID')
param authClientSecret = readEnvironmentVariable('AUTH_CLIENT_SECRET')
param allowedUsers = split(readEnvironmentVariable('ALLOWED_USERS'), ',')
