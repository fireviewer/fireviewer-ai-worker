[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ImageTag,
    [Parameter(Mandatory)][string]$ExpectedImageDigest,
    [Parameter(Mandatory)][string]$ExpectedArchiveSha256,
    [Parameter(Mandatory)][string]$ArtifactPath,
    [Parameter(Mandatory)][string]$SmokeRequestPath,
    [string]$Region = "eu-west-3",
    [string]$RepositoryName = "fireviewer-geo-gpu",
    [string]$RoleName = "fireviewer-geo-sagemaker-execution"
)

$ErrorActionPreference = "Stop"
if ($ImageTag -notmatch '^build-[0-9a-f]{20}$') {
    throw "The ECR image tag is not an immutable FireViewer build tag"
}
if ($ExpectedImageDigest -notmatch '^sha256:[0-9a-fA-F]{64}$') {
    throw "The expected ECR image digest is invalid"
}
if ($ExpectedArchiveSha256 -notmatch '^[0-9a-fA-F]{64}$') {
    throw "The expected archive SHA-256 is invalid"
}
$artifact = (Resolve-Path -LiteralPath $ArtifactPath).Path
$actualArchiveSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifact).Hash.ToLowerInvariant()
if ($actualArchiveSha256 -ne $ExpectedArchiveSha256.ToLowerInvariant()) {
    throw "The SageMaker model archive digest does not match its receipt"
}
$identity = aws sts get-caller-identity --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw "AWS authentication is required before publishing the model"
}
$accountId = [string]$identity.Account
$bucketName = "fireviewer-geo-ai-$accountId-$Region"
$remoteImage = aws ecr describe-images `
    --repository-name $RepositoryName `
    --image-ids "imageTag=$ImageTag" `
    --region $Region `
    --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $remoteImage.imageDetails.Count -ne 1) {
    throw "The immutable FireViewer ECR image is absent"
}
$actualImageDigest = [string]$remoteImage.imageDetails[0].imageDigest
if ($actualImageDigest -ne $ExpectedImageDigest.ToLowerInvariant()) {
    throw "The ECR image digest does not match its qualified receipt"
}
$imageUri = "$accountId.dkr.ecr.$Region.amazonaws.com/$RepositoryName@$actualImageDigest"
$role = aws iam get-role --role-name $RoleName --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw "The isolated FireViewer SageMaker role is absent"
}
$roleArn = [string]$role.Role.Arn
$shortRevision = $actualImageDigest.Substring(7, 16).ToLowerInvariant()
$modelName = "fireviewer-geo-$shortRevision"
$endpointConfigName = "fireviewer-geo-async-$shortRevision"
$artifactKey = "sagemaker/model-artifacts/$actualArchiveSha256/model.tar.gz"
$modelDataUrl = "s3://$bucketName/$artifactKey"
$smokeRequest = (Resolve-Path -LiteralPath $SmokeRequestPath).Path
$smokeSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $smokeRequest).Hash.ToLowerInvariant()
$smokeInputUrl = "s3://$bucketName/async/input/smoke/$smokeSha256/request.json"

$modelUploadRequired = $true
$remoteModelJson = aws s3api head-object `
    --bucket $bucketName `
    --key $artifactKey `
    --region $Region `
    --output json 2>$null
if ($LASTEXITCODE -eq 0) {
    $remoteModel = $remoteModelJson | ConvertFrom-Json
    $modelUploadRequired = -not (
        [int64]$remoteModel.ContentLength -eq (Get-Item -LiteralPath $artifact).Length -and
        [string]$remoteModel.Metadata.sha256 -eq $actualArchiveSha256
    )
}
if ($modelUploadRequired) {
    aws s3 cp $artifact $modelDataUrl `
        --region $Region `
        --sse AES256 `
        --metadata "sha256=$actualArchiveSha256,megaloc-revision=37bb43d65dd6388d1578052de5eb0bcdceb497e7,prithvi-revision=a3f2c410e45b8ac7417976614528a872f024d831" `
        --only-show-errors
    if ($LASTEXITCODE -ne 0) {
        throw "The qualified model artifact could not be uploaded"
    }
}
$smokeUploadRequired = $true
$remoteSmokeJson = aws s3api head-object `
    --bucket $bucketName `
    --key "async/input/smoke/$smokeSha256/request.json" `
    --region $Region `
    --output json 2>$null
if ($LASTEXITCODE -eq 0) {
    $remoteSmoke = $remoteSmokeJson | ConvertFrom-Json
    $smokeUploadRequired = -not (
        [int64]$remoteSmoke.ContentLength -eq (Get-Item -LiteralPath $smokeRequest).Length -and
        [string]$remoteSmoke.Metadata.sha256 -eq $smokeSha256
    )
}
if ($smokeUploadRequired) {
    aws s3 cp $smokeRequest $smokeInputUrl `
        --region $Region `
        --sse AES256 `
        --content-type application/json `
        --metadata "sha256=$smokeSha256,scope=first-bounded-gpu-smoke" `
        --only-show-errors
    if ($LASTEXITCODE -ne 0) {
        throw "The bounded smoke request could not be uploaded"
    }
}

$modelExists = $true
aws sagemaker describe-model --model-name $modelName --region $Region --output json 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    $modelExists = $false
}
if (-not $modelExists) {
    $modelInput = @{
        ModelName = $modelName
        PrimaryContainer = @{
            Image = $imageUri
            Mode = "SingleModel"
            ModelDataUrl = $modelDataUrl
            Environment = @{ FW_PRITHVI_TILE_BATCH_SIZE = "1" }
        }
        ExecutionRoleArn = $roleArn
        EnableNetworkIsolation = $true
        Tags = @(
            @{ Key = "Project"; Value = "FireViewer" },
            @{ Key = "Workstream"; Value = "GeoGPU" }
        )
    } | ConvertTo-Json -Depth 10 -Compress
    aws sagemaker create-model --region $Region --cli-input-json $modelInput --output json | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "SageMaker CreateModel failed"
    }
}

$configExists = $true
aws sagemaker describe-endpoint-config `
    --endpoint-config-name $endpointConfigName `
    --region $Region `
    --output json 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    $configExists = $false
}
if (-not $configExists) {
    $endpointConfig = @{
        EndpointConfigName = $endpointConfigName
        ProductionVariants = @(
            @{
                VariantName = "AllTraffic"
                ModelName = $modelName
                InitialInstanceCount = 1
                InstanceType = "ml.g4dn.2xlarge"
                InitialVariantWeight = 1.0
                ModelDataDownloadTimeoutInSeconds = 1200
                ContainerStartupHealthCheckTimeoutInSeconds = 600
                InferenceAmiVersion = "al2-ami-sagemaker-inference-gpu-2"
            }
        )
        AsyncInferenceConfig = @{
            ClientConfig = @{ MaxConcurrentInvocationsPerInstance = 1 }
            OutputConfig = @{
                S3OutputPath = "s3://$bucketName/async/output/"
                S3FailurePath = "s3://$bucketName/async/failure/"
            }
        }
        Tags = @(
            @{ Key = "Project"; Value = "FireViewer" },
            @{ Key = "Workstream"; Value = "GeoGPU" },
            @{ Key = "BillingState"; Value = "PreparedOnly" }
        )
    } | ConvertTo-Json -Depth 12 -Compress
    aws sagemaker create-endpoint-config `
        --region $Region `
        --cli-input-json $endpointConfig `
        --output json | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "SageMaker CreateEndpointConfig failed"
    }
}

$activationPlan = [ordered]@{
    schema = "fireviewer.aws-geo-async-plan.v1"
    region = $Region
    endpoint_name = $endpointConfigName
    endpoint_config_name = $endpointConfigName
    model_name = $modelName
    model_data_url = $modelDataUrl
    image_uri = $imageUri
    image_tag = $ImageTag
    image_digest = $actualImageDigest
    smoke_input_s3_uri = $smokeInputUrl
    smoke_input_sha256 = $smokeSha256
    instance_type = "ml.g4dn.2xlarge"
    min_capacity = 0
    max_capacity = 1
    endpoint_created = $false
    create_endpoint_authorized = $false
}
$activationPlan | ConvertTo-Json -Depth 8
