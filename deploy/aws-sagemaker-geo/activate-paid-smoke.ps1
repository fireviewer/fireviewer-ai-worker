[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$EndpointName,
    [Parameter(Mandatory)][string]$EndpointConfigName,
    [Parameter(Mandatory)][string]$SmokeInputS3Uri,
    [Parameter(Mandatory)][switch]$AuthorizePaidSmoke,
    [string]$Region = "eu-west-3"
)

$ErrorActionPreference = "Stop"
if (-not $AuthorizePaidSmoke) {
    throw "The paid GPU smoke must be explicitly authorized"
}
if ($EndpointName -notmatch '^fireviewer-geo-async-[0-9a-f]{16}$') {
    throw "The endpoint name is outside the isolated FireViewer Geo scope"
}
if ($EndpointConfigName -notmatch '^fireviewer-geo-async-[0-9a-f]{16}$') {
    throw "The endpoint configuration is outside the isolated FireViewer Geo scope"
}
if ($EndpointName -ne $EndpointConfigName) {
    throw "The bounded smoke endpoint must use its matching immutable endpoint configuration"
}
if ($SmokeInputS3Uri -notmatch '^s3://fireviewer-geo-ai-[0-9]{12}-[a-z0-9-]+/async/input/smoke/[0-9a-f]{64}/request\.json$') {
    throw "The smoke input is outside the immutable FireViewer Geo smoke prefix"
}

$endpointConfig = aws sagemaker describe-endpoint-config `
    --endpoint-config-name $EndpointConfigName `
    --region $Region `
    --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw "The immutable FireViewer Geo endpoint configuration does not exist"
}
$variant = $endpointConfig.ProductionVariants | Where-Object { $_.VariantName -eq "AllTraffic" }
if (
    $null -eq $endpointConfig.AsyncInferenceConfig -or
    $null -eq $variant -or
    [int]$variant.InitialInstanceCount -ne 1 -or
    [string]$variant.InstanceType -ne "ml.g4dn.2xlarge" -or
    [int]$endpointConfig.AsyncInferenceConfig.ClientConfig.MaxConcurrentInvocationsPerInstance -ne 1
) {
    throw "The endpoint configuration is not the bounded FireViewer Geo async profile"
}

$endpointExists = $true
aws sagemaker describe-endpoint --endpoint-name $EndpointName --region $Region --output json 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    $endpointExists = $false
}
$createdEndpoint = $false
$scalingSecured = $false
try {
    if (-not $endpointExists) {
        aws sagemaker create-endpoint `
            --endpoint-name $EndpointName `
            --endpoint-config-name $EndpointConfigName `
            --region $Region `
            --tags Key=Project,Value=FireViewer Key=Workstream,Value=GeoGPU Key=BillingState,Value=AuthorizedSmoke `
            --output json | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "SageMaker CreateEndpoint failed"
        }
        $createdEndpoint = $true
    }
    aws sagemaker wait endpoint-in-service --endpoint-name $EndpointName --region $Region
    if ($LASTEXITCODE -ne 0) {
        $failedEndpoint = aws sagemaker describe-endpoint `
            --endpoint-name $EndpointName `
            --region $Region `
            --output json | ConvertFrom-Json
        $failureReason = if ($null -ne $failedEndpoint.FailureReason) {
            [string]$failedEndpoint.FailureReason
        } else {
            "SageMaker returned no FailureReason"
        }
        throw "The bounded smoke endpoint did not become ready: $failureReason"
    }

    $resourceId = "endpoint/$EndpointName/variant/AllTraffic"
    aws application-autoscaling register-scalable-target `
        --service-namespace sagemaker `
        --resource-id $resourceId `
        --scalable-dimension sagemaker:variant:DesiredInstanceCount `
        --min-capacity 0 `
        --max-capacity 1 `
        --region $Region | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Scale-to-zero target registration failed"
    }

    $targetTracking = @{
        TargetValue = 1.0
        CustomizedMetricSpecification = @{
            MetricName = "ApproximateBacklogSizePerInstance"
            Namespace = "AWS/SageMaker"
            Dimensions = @(@{ Name = "EndpointName"; Value = $EndpointName })
            Statistic = "Average"
        }
        ScaleInCooldown = 300
        ScaleOutCooldown = 60
    } | ConvertTo-Json -Depth 8 -Compress
    aws application-autoscaling put-scaling-policy `
        --policy-name "$EndpointName-target-tracking" `
        --service-namespace sagemaker `
        --resource-id $resourceId `
        --scalable-dimension sagemaker:variant:DesiredInstanceCount `
        --policy-type TargetTrackingScaling `
        --target-tracking-scaling-policy-configuration $targetTracking `
        --region $Region | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Scale-to-zero target tracking policy failed"
    }

    $stepScaling = @{
        AdjustmentType = "ChangeInCapacity"
        MetricAggregationType = "Average"
        Cooldown = 60
        StepAdjustments = @(@{ MetricIntervalLowerBound = 0; ScalingAdjustment = 1 })
    } | ConvertTo-Json -Depth 8 -Compress
    $stepPolicy = aws application-autoscaling put-scaling-policy `
        --policy-name "$EndpointName-zero-to-one" `
        --service-namespace sagemaker `
        --resource-id $resourceId `
        --scalable-dimension sagemaker:variant:DesiredInstanceCount `
        --policy-type StepScaling `
        --step-scaling-policy-configuration $stepScaling `
        --region $Region `
        --output json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) {
        throw "Zero-to-one step scaling policy failed"
    }
    aws cloudwatch put-metric-alarm `
        --alarm-name "$EndpointName-has-backlog-without-capacity" `
        --metric-name HasBacklogWithoutCapacity `
        --namespace AWS/SageMaker `
        --statistic Average `
        --period 60 `
        --evaluation-periods 1 `
        --datapoints-to-alarm 1 `
        --threshold 1 `
        --comparison-operator GreaterThanOrEqualToThreshold `
        --dimensions "Name=EndpointName,Value=$EndpointName" `
        --alarm-actions $stepPolicy.PolicyARN `
        --treat-missing-data missing `
        --region $Region
    if ($LASTEXITCODE -ne 0) {
        throw "Zero-to-one backlog alarm failed"
    }
    $scalingSecured = $true

    $endpoint = aws sagemaker describe-endpoint `
        --endpoint-name $EndpointName `
        --region $Region `
        --output json | ConvertFrom-Json
    $tags = aws sagemaker list-tags `
        --resource-arn $endpoint.EndpointArn `
        --region $Region `
        --output json | ConvertFrom-Json
    if ($tags.Tags | Where-Object { $_.Key -eq "FirstSmokeState" }) {
        throw "The unique FireViewer GPU smoke was already reserved or queued"
    }
    aws sagemaker add-tags `
        --resource-arn $endpoint.EndpointArn `
        --tags Key=FirstSmokeState,Value=reserved `
        --region $Region | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "The unique smoke reservation could not be recorded"
    }

    $invocation = aws sagemaker-runtime invoke-endpoint-async `
        --endpoint-name $EndpointName `
        --input-location $SmokeInputS3Uri `
        --content-type application/json `
        --inference-id "fireviewer-first-bounded-smoke" `
        --region $Region `
        --output json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) {
        throw "The unique GPU smoke invocation failed to queue"
    }
    aws sagemaker add-tags `
        --resource-arn $endpoint.EndpointArn `
        --tags Key=FirstSmokeState,Value=queued `
        --region $Region | Out-Null

    [ordered]@{
        schema = "fireviewer.aws-geo-paid-smoke-started.v1"
        endpoint_name = $EndpointName
        min_capacity = 0
        max_capacity = 1
        inference_id = "fireviewer-first-bounded-smoke"
        output_location = [string]$invocation.OutputLocation
        failure_location = [string]$invocation.FailureLocation
    } | ConvertTo-Json -Depth 5
} catch {
    if ($createdEndpoint -and -not $scalingSecured) {
        aws sagemaker delete-endpoint --endpoint-name $EndpointName --region $Region | Out-Null
    }
    throw
}
