[CmdletBinding()]
param(
    [string]$Region = "eu-west-3",
    [string]$ResourceGroup = "rg-fireviewer-api-frc",
    [string]$AzureIdentityName = "id-fireviewer-eve-bedrock",
    [Parameter(Mandatory)][string]$Audience,
    [string]$RoleName = "fireviewer-eve-pixtral",
    [string]$InferenceProfileId = "eu.mistral.pixtral-large-2502-v1:0",
    [string]$FoundationModelId = "mistral.pixtral-large-2502-v1:0"
)

$ErrorActionPreference = "Stop"

function Invoke-AwsJson {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $result = & aws @Arguments --output json
    if ($LASTEXITCODE -ne 0) {
        throw "AWS CLI failed: aws $($Arguments -join ' ')"
    }
    if ([string]::IsNullOrWhiteSpace(($result -join "`n"))) {
        return $null
    }
    return (($result -join "`n") | ConvertFrom-Json)
}

$awsIdentity = Invoke-AwsJson -Arguments @("sts", "get-caller-identity")
$accountId = [string]$awsIdentity.Account
$profile = Invoke-AwsJson -Arguments @(
    "bedrock", "get-inference-profile",
    "--region", $Region,
    "--inference-profile-identifier", $InferenceProfileId
)
if ($profile.status -ne "ACTIVE" -or $profile.inferenceProfileId -ne $InferenceProfileId) {
    throw "The selected Bedrock inference profile is not active."
}
if (-not ($profile.models.modelArn -match "/$([regex]::Escape($FoundationModelId))$")) {
    throw "The selected inference profile does not route to the pinned foundation model."
}

$azureIdentity = & az identity show `
    --resource-group $ResourceGroup `
    --name $AzureIdentityName `
    --query '{principalId:principalId,tenantId:tenantId}' `
    --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $azureIdentity.principalId -or -not $azureIdentity.tenantId) {
    throw "The dedicated Azure Eve identity could not be resolved."
}

$oidcHost = "sts.windows.net/$($azureIdentity.tenantId)/"
$trustPolicy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Effect = "Allow"
            Principal = @{
                Federated = "arn:aws:iam::${accountId}:oidc-provider/$oidcHost"
            }
            Action = "sts:AssumeRoleWithWebIdentity"
            Condition = @{
                StringEquals = @{
                    "${oidcHost}:aud" = $Audience
                    "${oidcHost}:sub" = [string]$azureIdentity.principalId
                }
            }
        }
    )
} | ConvertTo-Json -Depth 10 -Compress

$roleExists = $true
& aws iam get-role --role-name $RoleName --output json 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    $roleExists = $false
}
if (-not $roleExists) {
    Invoke-AwsJson -Arguments @(
        "iam", "create-role",
        "--role-name", $RoleName,
        "--assume-role-policy-document", $trustPolicy,
        "--description", "FireViewer Eve managed VL point supervisor on Bedrock Pixtral",
        "--tags", "Key=Application,Value=FireViewer", "Key=Component,Value=PointSupervisor"
    ) | Out-Null
} else {
    Invoke-AwsJson -Arguments @(
        "iam", "update-assume-role-policy",
        "--role-name", $RoleName,
        "--policy-document", $trustPolicy
    ) | Out-Null
}

$invokePolicy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Sid = "InvokeOnlyPinnedPixtralProfile"
            Effect = "Allow"
            Action = "bedrock:InvokeModel"
            Resource = @(
                [string]$profile.inferenceProfileArn,
                "arn:aws:bedrock:*::foundation-model/$FoundationModelId"
            )
        }
    )
} | ConvertTo-Json -Depth 10 -Compress
Invoke-AwsJson -Arguments @(
    "iam", "put-role-policy",
    "--role-name", $RoleName,
    "--policy-name", "fireviewer-eve-pixtral-converse",
    "--policy-document", $invokePolicy
) | Out-Null

$role = Invoke-AwsJson -Arguments @("iam", "get-role", "--role-name", $RoleName)
[ordered]@{
    schema = "fireviewer.aws-eve-pixtral-role.v1"
    role_arn = $role.Role.Arn
    azure_principal_id = [string]$azureIdentity.principalId
    audience = $Audience
    inference_profile_id = $InferenceProfileId
    inference_profile_arn = [string]$profile.inferenceProfileArn
    foundation_model_id = $FoundationModelId
    model_invoked = $false
} | ConvertTo-Json -Depth 5
