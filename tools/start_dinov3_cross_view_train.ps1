[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$BundleRoot = $env:FIREVIEWER_CROSS_VIEW_BUNDLE_ROOT,
    [string]$Output = "data\training\dinov3-cross-view-retrieval-v1",
    [string]$LogRoot = $env:TEMP,
    [int]$Epochs = 40,
    [int]$BatchSize = 4,
    [int]$GradientAccumulationSteps = 8
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$outputPath = [IO.Path]::GetFullPath((Join-Path $repositoryRoot $Output))
$pidPath = Join-Path $outputPath "run.pid"
$stdoutPath = Join-Path $LogRoot "fireviewer-dinov3-cross-view-v1.out.log"
$stderrPath = Join-Path $LogRoot "fireviewer-dinov3-cross-view-v1.err.log"

if ([string]::IsNullOrWhiteSpace($BundleRoot) -or -not (Test-Path -LiteralPath $BundleRoot)) {
    throw "Set FIREVIEWER_CROSS_VIEW_BUNDLE_ROOT to the extracted cross-view bundle."
}

if (Test-Path -LiteralPath $pidPath) {
    $existingPid = [int](Get-Content -LiteralPath $pidPath -Raw).Trim()
    if (Get-Process -Id $existingPid -ErrorAction SilentlyContinue) {
        throw "DINOv3 cross-view train is already running with PID $existingPid"
    }
}

New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
$pythonCommand = Get-Command $Python -ErrorAction Stop
$arguments = @(
    "-m", "training.train_dinov3_cross_view", "train",
    "--bundle-root", $BundleRoot,
    "--model-path", "data\models\dinov3-vitb16-pretrain-lvd1689m",
    "--output", $Output,
    "--epochs", $Epochs,
    "--batch-size", $BatchSize,
    "--gradient-accumulation-steps", $GradientAccumulationSteps,
    "--learning-rate", "1e-5",
    "--head-learning-rate", "5e-5",
    "--warmup-ratio", "0.05",
    "--early-stop-patience", "8",
    "--resume-from", "auto",
    "--verify-file-hashes"
)

$startParameters = @{
    FilePath = $pythonCommand.Source
    ArgumentList = $arguments
    WorkingDirectory = $repositoryRoot
    RedirectStandardOutput = $stdoutPath
    RedirectStandardError = $stderrPath
    WindowStyle = "Hidden"
    PassThru = $true
}
$process = Start-Process @startParameters

[IO.File]::WriteAllText($pidPath, "$($process.Id)`n", [Text.UTF8Encoding]::new($false))
[pscustomobject]@{
    Pid = $process.Id
    Output = $outputPath
    Stdout = $stdoutPath
    Stderr = $stderrPath
}
