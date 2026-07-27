#!/usr/bin/env bash
set -euo pipefail

ROOT=/workspace/firewarning-prithvi
BUNDLE="$ROOT/bundles/burned-area-segmentation-v1.zip"
BUNDLE_SIZE=27926097197
BUNDLE_SHA256=85c2f17248528ebbd5aa8395e72435ba5a12626bb5a53f5730109b11ea5dde36
INPUT_ROOT="$ROOT/inputs/burned-area-segmentation-v1"
PERSISTENT_DATASET_ROOT="$INPUT_ROOT/materialized"
DATASET_ROOT="${FW_PRITHVI_RUNTIME_DATASET_ROOT:-/tmp/firewarning-prithvi-materialized}"
DATASET_REPORT_SHA256=90e3002926713e2a204c2dcb5af4fdf07dd4de9b2dc1d51bd574860974b8d7f5
CRITICAL_REPORT="$ROOT/critical/prithvi-geographic-critical-test-v1/report.json"
OUTPUT_ROOT="$ROOT/output/prithvi-burnscars"
CODE_ROOT="$ROOT/code"
VENV="$ROOT/venv"
LOG_ROOT="$ROOT/logs"

export HF_HOME="$ROOT/hf-cache"
export TORCH_HOME="$ROOT/torch-cache"
export PYTHONPATH="$CODE_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export GDAL_NUM_THREADS=1
export TORCH_ALLOW_TF32_CUBLAS_OVERRIDE=1

mkdir -p "$LOG_ROOT" "$OUTPUT_ROOT" "$TORCH_HOME"
exec >>"$LOG_ROOT/campaign.log" 2>&1

stage() {
  printf '%s stage=%s\n' "$(date --iso-8601=seconds)" "$1"
}

fail() {
  stage "failed:$1"
  printf '%s\n' "$1" >"$LOG_ROOT/campaign.failed"
  exit 1
}

stage waiting_for_dataset
while true; do
  observed_size=0
  if [[ -f "$BUNDLE" ]]; then
    observed_size=$(stat -c %s "$BUNDLE")
  fi
  if [[ "$observed_size" -eq "$BUNDLE_SIZE" ]]; then
    break
  fi
  if [[ "$observed_size" -gt "$BUNDLE_SIZE" ]]; then
    fail "bundle_size_exceeds_contract:$observed_size"
  fi
  if ! pgrep -f '^curl -L .*burned-area-segmentation-v1.zip' >/dev/null; then
    fail "dataset_download_stopped_at:$observed_size"
  fi
  printf '%s dataset_bytes=%s/%s\n' \
    "$(date --iso-8601=seconds)" "$observed_size" "$BUNDLE_SIZE"
  sleep 20
done

stage verifying_bundle
observed_sha256=$(sha256sum "$BUNDLE" | awk '{print $1}')
[[ "$observed_sha256" == "$BUNDLE_SHA256" ]] ||
  fail "bundle_sha256_mismatch:$observed_sha256"
touch "$LOG_ROOT/bundle.verified"

stage preparing_materialized_dataset
if [[ ! -f "$INPUT_ROOT/preparation-report.json" ]]; then
  [[ ! -e "$INPUT_ROOT.partial" ]] || fail "interrupted_input_staging_present"
  (
    cd "$CODE_ROOT/tools/dataset_hub"
    "$VENV/bin/python" prepare_mvp_train_inputs.py prithvi \
      --bundle-dir "$ROOT/bundles" \
      --destination "$INPUT_ROOT"
  )
fi
[[ -f "$PERSISTENT_DATASET_ROOT/materialization-report.json" ]] ||
  fail "materialization_report_missing"
touch "$LOG_ROOT/dataset.ready"

stage staging_runtime_dataset
runtime_marker="$DATASET_ROOT/.firewarning-materialization-report-sha256"
if [[ ! -f "$runtime_marker" ]] ||
  [[ "$(cat "$runtime_marker")" != "$DATASET_REPORT_SHA256" ]]; then
  runtime_staging="$DATASET_ROOT.partial"
  [[ ! -e "$DATASET_ROOT" ]] || fail "runtime_dataset_stale_or_unverified"
  [[ ! -e "$runtime_staging" ]] || fail "runtime_dataset_staging_already_exists"
  mkdir -p "$runtime_staging"
  (
    cd "$PERSISTENT_DATASET_ROOT"
    tar -cf - .
  ) | (
    cd "$runtime_staging"
    tar -xf -
  )
  runtime_report_sha256=$(sha256sum \
    "$runtime_staging/materialization-report.json" | awk '{print $1}')
  [[ "$runtime_report_sha256" == "$DATASET_REPORT_SHA256" ]] ||
    fail "runtime_dataset_report_sha256_mismatch:$runtime_report_sha256"
  persistent_files=$(find "$PERSISTENT_DATASET_ROOT" -type f | wc -l)
  runtime_files=$(find "$runtime_staging" -type f | wc -l)
  [[ "$runtime_files" -eq "$persistent_files" ]] ||
    fail "runtime_dataset_file_count_mismatch:$runtime_files/$persistent_files"
  printf '%s\n' "$DATASET_REPORT_SHA256" \
    >"$runtime_staging/.firewarning-materialization-report-sha256"
  mv "$runtime_staging" "$DATASET_ROOT"
fi

stage preflight
(
  cd "$CODE_ROOT"
  "$VENV/bin/python" -m training.train_prithvi_burnscars preflight \
    --geographic-test-report "$CRITICAL_REPORT" \
    --dataset-root "$DATASET_ROOT" \
    --output "$OUTPUT_ROOT/preflight" \
    --verify-files
)
touch "$LOG_ROOT/preflight.passed"

stage smoke
smoke_started=$(date +%s)
(
  cd "$CODE_ROOT"
  "$VENV/bin/python" -m training.train_prithvi_burnscars smoke \
    --geographic-test-report "$CRITICAL_REPORT" \
    --dataset-root "$DATASET_ROOT" \
    --output "$OUTPUT_ROOT/smoke" \
    --batch-size 24 \
    --workers 8 \
    --epochs 1 \
    --checkpoint-steps 1 \
    --verify-files \
    --confirm-training
)
smoke_seconds=$(($(date +%s) - smoke_started))
printf '%s\n' "$smoke_seconds" >"$LOG_ROOT/smoke-seconds.txt"
touch "$LOG_ROOT/smoke.passed"

stage train
touch "$LOG_ROOT/training.started"
(
  cd "$CODE_ROOT"
  "$VENV/bin/python" -m training.train_prithvi_burnscars train \
    --geographic-test-report "$CRITICAL_REPORT" \
    --dataset-root "$DATASET_ROOT" \
    --output "$OUTPUT_ROOT/train" \
    --batch-size 24 \
    --workers 8 \
    --epochs 10 \
    --checkpoint-steps 500 \
    --resume-from-checkpoint auto \
    --verify-files \
    --confirm-training
)
touch "$LOG_ROOT/training.completed"
stage completed
