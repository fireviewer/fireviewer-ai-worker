[CmdletBinding()]
param(
    [string]$Region = "eu-west-3",
    [string]$RepositoryName = "fireviewer-geo-gpu",
    [string]$RoleName = "fireviewer-geo-sagemaker-execution"
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

$identity = Invoke-AwsJson -Arguments @("sts", "get-caller-identity")
$accountId = [string]$identity.Account
$bucketName = "fireviewer-geo-ai-$accountId-$Region"
$repositoryArn = "arn:aws:ecr:${Region}:${accountId}:repository/$RepositoryName"
$bucketArn = "arn:aws:s3:::$bucketName"

$repositoryExists = $true
& aws ecr describe-repositories --repository-names $RepositoryName --region $Region --output json 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    $repositoryExists = $false
}
if (-not $repositoryExists) {
    Invoke-AwsJson -Arguments @(
        "ecr", "create-repository",
        "--repository-name", $RepositoryName,
        "--region", $Region,
        "--image-tag-mutability", "IMMUTABLE",
        "--image-scanning-configuration", "scanOnPush=true",
        "--encryption-configuration", "encryptionType=AES256",
        "--tags", "Key=Project,Value=FireViewer", "Key=Workstream,Value=GeoGPU"
    ) | Out-Null
}

$ecrLifecycle = @{
    rules = @(
        @{
            rulePriority = 1
            description = "Expire untagged build layers after one day"
            selection = @{
                tagStatus = "untagged"
                countType = "sinceImagePushed"
                countUnit = "days"
                countNumber = 1
            }
            action = @{ type = "expire" }
        },
        @{
            rulePriority = 2
            description = "Retain the five newest immutable FireViewer images"
            selection = @{
                tagStatus = "tagged"
                tagPrefixList = @("build-")
                countType = "imageCountMoreThan"
                countNumber = 5
            }
            action = @{ type = "expire" }
        }
    )
} | ConvertTo-Json -Depth 10 -Compress
Invoke-AwsJson -Arguments @(
    "ecr", "put-lifecycle-policy",
    "--repository-name", $RepositoryName,
    "--region", $Region,
    "--lifecycle-policy-text", $ecrLifecycle
) | Out-Null

$bucketExists = $true
& aws s3api head-bucket --bucket $bucketName 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    $bucketExists = $false
}
if (-not $bucketExists) {
    Invoke-AwsJson -Arguments @(
        "s3api", "create-bucket",
        "--bucket", $bucketName,
        "--region", $Region,
        "--create-bucket-configuration", "LocationConstraint=$Region"
    ) | Out-Null
}

Invoke-AwsJson -Arguments @(
    "s3api", "put-public-access-block",
    "--bucket", $bucketName,
    "--public-access-block-configuration",
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
) | Out-Null
Invoke-AwsJson -Arguments @(
    "s3api", "put-bucket-ownership-controls",
    "--bucket", $bucketName,
    "--ownership-controls", '{"Rules":[{"ObjectOwnership":"BucketOwnerEnforced"}]}'
) | Out-Null
Invoke-AwsJson -Arguments @(
    "s3api", "put-bucket-encryption",
    "--bucket", $bucketName,
    "--server-side-encryption-configuration",
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":false}]}'
) | Out-Null
Invoke-AwsJson -Arguments @(
    "s3api", "put-bucket-versioning",
    "--bucket", $bucketName,
    "--versioning-configuration", "Status=Enabled"
) | Out-Null
Invoke-AwsJson -Arguments @(
    "s3api", "put-bucket-tagging",
    "--bucket", $bucketName,
    "--tagging", '{"TagSet":[{"Key":"Project","Value":"FireViewer"},{"Key":"Workstream","Value":"GeoGPU"}]}'
) | Out-Null

$bucketPolicy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Sid = "DenyInsecureTransport"
            Effect = "Deny"
            Principal = "*"
            Action = "s3:*"
            Resource = @($bucketArn, "$bucketArn/*")
            Condition = @{ Bool = @{ "aws:SecureTransport" = "false" } }
        }
    )
} | ConvertTo-Json -Depth 10 -Compress
Invoke-AwsJson -Arguments @(
    "s3api", "put-bucket-policy",
    "--bucket", $bucketName,
    "--policy", $bucketPolicy
) | Out-Null

$s3Lifecycle = @{
    Rules = @(
        @{
            ID = "abort-incomplete-multipart"
            Status = "Enabled"
            Filter = @{ Prefix = "" }
            AbortIncompleteMultipartUpload = @{ DaysAfterInitiation = 7 }
        },
        @{
            ID = "expire-transient-async-payloads"
            Status = "Enabled"
            Filter = @{ Prefix = "async/" }
            Expiration = @{ Days = 30 }
            NoncurrentVersionExpiration = @{ NoncurrentDays = 30 }
        }
    )
} | ConvertTo-Json -Depth 10 -Compress
Invoke-AwsJson -Arguments @(
    "s3api", "put-bucket-lifecycle-configuration",
    "--bucket", $bucketName,
    "--lifecycle-configuration", $s3Lifecycle
) | Out-Null

$trustPolicy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Effect = "Allow"
            Principal = @{ Service = "sagemaker.amazonaws.com" }
            Action = "sts:AssumeRole"
            Condition = @{
                StringEquals = @{ "aws:SourceAccount" = $accountId }
                ArnLike = @{ "aws:SourceArn" = "arn:aws:sagemaker:${Region}:${accountId}:*" }
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
        "--description", "FireViewer isolated MegaLoc and Prithvi SageMaker execution role",
        "--tags", "Key=Project,Value=FireViewer", "Key=Workstream,Value=GeoGPU"
    ) | Out-Null
} else {
    Invoke-AwsJson -Arguments @(
        "iam", "update-assume-role-policy",
        "--role-name", $RoleName,
        "--policy-document", $trustPolicy
    ) | Out-Null
}

$executionPolicy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Sid = "LocateFireViewerGeoBucket"
            Effect = "Allow"
            Action = "s3:GetBucketLocation"
            Resource = $bucketArn
        },
        @{
            Sid = "ListFireViewerGeoBucket"
            Effect = "Allow"
            Action = "s3:ListBucket"
            Resource = $bucketArn
        },
        @{
            Sid = "ReadFireViewerModelsAndAsyncInputs"
            Effect = "Allow"
            Action = @("s3:GetObject", "s3:GetObjectVersion")
            Resource = @(
                "$bucketArn/models/*",
                "$bucketArn/sagemaker/model-artifacts/*",
                "$bucketArn/async/input/*"
            )
        },
        @{
            Sid = "WriteFireViewerAsyncResults"
            Effect = "Allow"
            Action = "s3:PutObject"
            Resource = @("$bucketArn/async/output/*", "$bucketArn/async/failure/*")
        },
        @{
            Sid = "AuthorizeEcrPull"
            Effect = "Allow"
            Action = "ecr:GetAuthorizationToken"
            Resource = "*"
        },
        @{
            Sid = "PullFireViewerGeoImage"
            Effect = "Allow"
            Action = @(
                "ecr:BatchCheckLayerAvailability",
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage"
            )
            Resource = $repositoryArn
        },
        @{
            Sid = "CreateFireViewerSageMakerLogGroups"
            Effect = "Allow"
            Action = "logs:CreateLogGroup"
            Resource = "arn:aws:logs:${Region}:${accountId}:log-group:/aws/sagemaker/Endpoints/fireviewer-geo-*"
        },
        @{
            Sid = "WriteFireViewerSageMakerLogStreams"
            Effect = "Allow"
            Action = @("logs:CreateLogStream", "logs:PutLogEvents")
            Resource = "arn:aws:logs:${Region}:${accountId}:log-group:/aws/sagemaker/Endpoints/fireviewer-geo-*:log-stream:*"
        }
    )
} | ConvertTo-Json -Depth 10 -Compress
Invoke-AwsJson -Arguments @(
    "iam", "put-role-policy",
    "--role-name", $RoleName,
    "--policy-name", "fireviewer-geo-sagemaker-runtime",
    "--policy-document", $executionPolicy
) | Out-Null

$repository = Invoke-AwsJson -Arguments @(
    "ecr", "describe-repositories",
    "--repository-names", $RepositoryName,
    "--region", $Region
)
$role = Invoke-AwsJson -Arguments @("iam", "get-role", "--role-name", $RoleName)

[ordered]@{
    schema = "fireviewer.aws-geo-resources.v1"
    region = $Region
    bucket = $bucketName
    ecr_repository = $repository.repositories[0].repositoryUri
    role_arn = $role.Role.Arn
    endpoint_created = $false
} | ConvertTo-Json -Depth 5
