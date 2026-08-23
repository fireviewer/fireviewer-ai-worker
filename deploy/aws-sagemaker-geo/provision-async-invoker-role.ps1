[CmdletBinding()]
param(
    [string]$Region = "eu-west-3",
    [string]$ResourceGroup = "rg-fireviewer-api-frc",
    [string]$AzureIdentityName = "id-fireviewer-geo-cpu",
    [Parameter(Mandatory)][string]$Audience,
    [string]$RoleName = "fireviewer-geo-async-invoker",
    [Parameter(Mandatory)][string]$EndpointName
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

if ($EndpointName -notmatch '^fireviewer-geo-async-[0-9a-f]{16}$') {
    throw "The endpoint name must be one immutable FireViewer Async endpoint revision."
}
if ($Audience -notmatch '^api://[0-9a-f-]{36}$') {
    throw "The Azure-to-AWS federation audience is invalid."
}

$identity = Invoke-AwsJson -Arguments @("sts", "get-caller-identity")
$accountId = [string]$identity.Account
$bucketName = "fireviewer-geo-ai-$accountId-$Region"
$bucketArn = "arn:aws:s3:::$bucketName"
$endpointArn = "arn:aws:sagemaker:${Region}:${accountId}:endpoint/$EndpointName"

$azureIdentity = & az identity show `
    --resource-group $ResourceGroup `
    --name $AzureIdentityName `
    --query '{principalId:principalId,tenantId:tenantId}' `
    --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $azureIdentity.principalId -or -not $azureIdentity.tenantId) {
    throw "The dedicated Azure managed identity could not be resolved."
}

$oidcHost = "sts.windows.net/$($azureIdentity.tenantId)/"
$providerArn = "arn:aws:iam::${accountId}:oidc-provider/$oidcHost"
$trustPolicy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Effect = "Allow"
            Principal = @{ Federated = $providerArn }
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
        "--description", "FireViewer Azure geo CPU access to one SageMaker Async endpoint revision",
        "--tags", "Key=Application,Value=FireViewer", "Key=Component,Value=GeoAsyncInvoker"
    ) | Out-Null
} else {
    Invoke-AwsJson -Arguments @(
        "iam", "update-assume-role-policy",
        "--role-name", $RoleName,
        "--policy-document", $trustPolicy
    ) | Out-Null
}

$invokerPolicy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Sid = "InvokeOneFireViewerAsyncEndpoint"
            Effect = "Allow"
            Action = "sagemaker:InvokeEndpointAsync"
            Resource = $endpointArn
        },
        @{
            Sid = "WriteAsyncInputsOnly"
            Effect = "Allow"
            Action = "s3:PutObject"
            Resource = "$bucketArn/async/input/*"
        },
        @{
            Sid = "ReadAsyncResultsOnly"
            Effect = "Allow"
            Action = "s3:GetObject"
            Resource = @(
                "$bucketArn/async/output/*",
                "$bucketArn/async/failure/*"
            )
        }
    )
} | ConvertTo-Json -Depth 10 -Compress

Invoke-AwsJson -Arguments @(
    "iam", "put-role-policy",
    "--role-name", $RoleName,
    "--policy-name", "fireviewer-geo-one-endpoint-async-invoke",
    "--policy-document", $invokerPolicy
) | Out-Null

$role = Invoke-AwsJson -Arguments @("iam", "get-role", "--role-name", $RoleName)
[ordered]@{
    schema = "fireviewer.aws-geo-async-invoker.v1"
    role_arn = $role.Role.Arn
    azure_principal_id = [string]$azureIdentity.principalId
    audience = $Audience
    endpoint_arn = $endpointArn
    input_prefix = "s3://$bucketName/async/input/"
    output_prefixes = @(
        "s3://$bucketName/async/output/",
        "s3://$bucketName/async/failure/"
    )
    endpoint_changed = $false
    endpoint_invoked = $false
} | ConvertTo-Json -Depth 5
