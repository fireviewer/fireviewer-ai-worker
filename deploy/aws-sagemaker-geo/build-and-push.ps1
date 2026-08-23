[CmdletBinding()]
param(
    [string]$Region = "eu-west-3",
    [string]$RepositoryName = "fireviewer-geo-gpu",
    [string]$LocalImage = "fireviewer-geo-gpu:local"
)

$ErrorActionPreference = "Stop"
$identity = aws sts get-caller-identity --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw "AWS authentication is required before pushing the image"
}
$accountId = [string]$identity.Account
$registry = "$accountId.dkr.ecr.$Region.amazonaws.com"
$imageId = docker image inspect $LocalImage --format "{{.Id}}"
if ($LASTEXITCODE -ne 0 -or $imageId -notmatch '^sha256:[0-9a-f]{64}$') {
    throw "The qualified local FireViewer image is absent"
}
$tag = "build-$($imageId.Substring(7, 20))"
$remoteImage = "$registry/${RepositoryName}:$tag"

$password = aws ecr get-login-password --region $Region
if ($LASTEXITCODE -ne 0) {
    throw "ECR authorization failed"
}
$password | docker login --username AWS --password-stdin $registry | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker could not authenticate to ECR"
}
docker tag $LocalImage $remoteImage
docker push $remoteImage
if ($LASTEXITCODE -ne 0) {
    throw "Docker could not push the FireViewer image"
}
$remote = aws ecr describe-images `
    --repository-name $RepositoryName `
    --image-ids "imageTag=$tag" `
    --region $Region `
    --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw "The pushed ECR image could not be qualified"
}

[ordered]@{
    schema = "fireviewer.aws-geo-image-receipt.v1"
    image_uri = $remoteImage
    image_tag = $tag
    image_digest = [string]$remote.imageDetails[0].imageDigest
    endpoint_created = $false
} | ConvertTo-Json -Depth 5
