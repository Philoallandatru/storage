#!/usr/bin/env bash
# ============================================================================
# ssd_mlperf_benchmark.sh — MLPerf Storage Benchmark per SSD
#
# Layer 3 of the comprehensive SSD test plan.
# Runs Training + Checkpointing benchmarks on a single SSD.
#
# Usage:
#   bash scripts/ssd_mlperf_benchmark.sh <vendor_id>          # single disk
#   bash scripts/ssd_mlperf_benchmark.sh all                  # all 4 disks
#   bash scripts/ssd_mlperf_benchmark.sh <vid> --dry-run      # plan only
#
# Vendor IDs: wd_sn570, biwin_x570, zhitai_ti600, seagate_fc530
#
# Disk capacity summary:
#   WD (201GB free)     → ckpt-8b only (105 GiB)
#   ZhiTai (196GB free) → ckpt-8b only (105 GiB)
#   Biwin (564GB free)  → all models
#   Seagate (378GB free)→ retinanet+flux+ckpt-8b
# ============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# Activate the project venv so mlpstorage, dlio_benchmark, mpirun resolution all work
# shellcheck source=/dev/null
source "$PROJECT_DIR/.venv/bin/activate"
source "$SCRIPT_DIR/cross_vendor_lib.sh"

# ---- Config ----

# Model definitions: each entry has "name|accelerator|accel_count|host_mem_gb|dataset_gb"
# These are tuned so dataset fits on target disks.
declare -ra TRAINING_MODELS=(
  "retinanet|b200|1|16|80"
  "flux|b200|1|16|80"
  "cosmoflow|h100|1|16|80"
  "resnet50|h100|2|32|160"
)

# Checkpointing: "model|num_processes|total_gib"
# NOTE: np must match 3D parallelism in YAML config (llama3_8b.yaml has dp=1,tp=1,pp=1)
# For multi-process: add --param model.parallelism.data=<np>
declare -ra CHECKPOINT_MODELS=(
  "llama3-8b|1|105"
)

RESULTS_ROOT=""     # set per-disk
DATA_DIR=""         # set per-disk
SSH_HOSTS="127.0.0.1"
ALLOW_ROOT="--allow-run-as-root"
OPEN_FLAG="--open"
VERBOSITY="--stream-log-level INFO"
STORAGE_FLAG="--file"
# EXTRA flags for 'run' subcommand only (not accepted by 'datasize')
RUN_EXTRA="${RUN_EXTRA:---skip-validation --skip-timeseries}"
MPI_SETTINGS="${MPI_SETTINGS:---mpi-btl vader}"
# Allow env override: MPI_SETTINGS="--mpi-btl tcp"  # if vader fails

# ---- Functions ----

usage() {
  echo "Usage: $0 <vendor_id|all> [--dry-run]"
  echo "  vendor_id: wd_sn570, biwin_x570, zhitai_ti600, seagate_fc530"
  echo "  all: run on all 4 disks"
  exit 1
}

check_requirements() {
  if ! command -v mpirun &>/dev/null; then
    echo "ERROR: mpirun not found. Install openmpi-bin."
    return 1
  fi
  if ! command -v mlpstorage &>/dev/null && ! command -v uv &>/dev/null; then
    # mlpstorage is usually invoked via uv run
    if [ ! -f "$PROJECT_DIR/.venv/bin/mlpstorage" ]; then
      echo "ERROR: mlpstorage not found. Run 'uv sync' first."
      return 1
    fi
  fi
  return 0
}

mlp() {
  # Run mlpstorage from the project venv
  "$PROJECT_DIR/.venv/bin/mlpstorage" "$@"
}

check_free_space() {
  local mount="$1"
  local needed_gb="$2"
  local free_gb
  free_gb=$(df --output=avail "$mount" 2>/dev/null | tail -1)
  free_gb=$((free_gb / 1024 / 1024))  # KB → GiB
  echo "$free_gb"
}

run_datasize() {
  local bench_type="$1"  # training or checkpointing
  local model="$2"
  shift 2
  local extra_args=("$@")

  echo "--- [datasize] $bench_type $model ---"
  local out
  out=$(mlp "$bench_type" datasize --what-if "$@" 2>&1) || true

  # Extract total disk space
  local total_gb
  total_gb=$(echo "$out" | grep "Total disk space required" | grep -oP '\d+\.?\d*(?=GiB)' || echo "0")
  if [ "$total_gb" = "0" ]; then
    total_gb=$(echo "$out" | grep "Total GiB required for all ranks" | grep -oP '\d+\.?\d*(?=GiB)' || echo "0")
  fi
  echo "$total_gb" | tr -d '[:space:]'
}

benchmark_checkpointing() {
  local vid="$1"
  local model="$2"
  local np="$3"
  local total_gib="$4"

  local ckpt_dir="$RESULTS_ROOT/checkpoints/$model"
  mkdir -p "$ckpt_dir"

  echo ""
  echo "================================================================"
  echo "  CHECKPOINTING: $model (np=$np, ~${total_gib}GiB)"
  echo "  DISK: $vid → $VENDOR_MOUNT"
  echo "================================================================"

  # Step 1: datasize (quick verification)
  echo ""
  echo "--- datasize ---"
  mlp checkpointing datasize \
    --model "$model" \
    --num-processes "$np" \
    --hosts "$SSH_HOSTS" \
    --client-host-memory-in-gb 64 \
    --checkpoint-folder "$ckpt_dir" \
    --results-dir "$RESULTS_ROOT" \
    $OPEN_FLAG --oversubscribe $ALLOW_ROOT \
    $VERBOSITY $STORAGE_FLAG \
    --what-if 2>&1 | head -30

  # Step 2: run 1 write + 1 read
  echo ""
  echo "--- run ---"
  mlp checkpointing run \
    --model "$model" \
    --num-processes "$np" \
    --hosts "$SSH_HOSTS" \
    --client-host-memory-in-gb 64 \
    --checkpoint-folder "$ckpt_dir" \
    --num-checkpoints-write 1 \
    --num-checkpoints-read 1 \
    --results-dir "$RESULTS_ROOT" \
    $OPEN_FLAG $ALLOW_ROOT --oversubscribe $MPI_SETTINGS \
    $VERBOSITY $STORAGE_FLAG $RUN_EXTRA 2>&1 | tee -a "$RESULTS_ROOT/${model}_run.log"

  echo "--- checkpointing $model done ---"
}

benchmark_training() {
  local vid="$1"
  local model="$2"
  local accel="$3"
  local num_acc="$4"
  local host_mem="$5"
  local total_gib="$6"

  local data_dir="$DATA_DIR/$model"
  local run_data_dir="$data_dir/data"
  mkdir -p "$run_data_dir"

  echo ""
  echo "================================================================"
  echo "  TRAINING: $model (${accel}x${num_acc}, ${host_mem}GB host mem)"
  echo "  DISK: $vid → $VENDOR_MOUNT"
  echo "  Dataset: ~${total_gib}GiB"
  echo "================================================================"

  # Step 1: datasize
  echo ""
  echo "--- datasize ---"
  mlp training datasize \
    --model "$model" \
    --accelerator-type "$accel" \
    --max-accelerators "$num_acc" \
    --hosts "$SSH_HOSTS" \
    --client-host-memory-in-gb "$host_mem" \
    --num-client-hosts 1 \
    --results-dir "$RESULTS_ROOT" \
    $OPEN_FLAG --oversubscribe $ALLOW_ROOT \
    $VERBOSITY $STORAGE_FLAG \
    --what-if 2>&1 | head -30

  # Step 2: datagen (generate data on the SSD)
  echo ""
  echo "--- datagen ---"
  local datagen_cmd
  datagen_cmd=$(mlp training datasize \
    --model "$model" \
    --accelerator-type "$accel" \
    --max-accelerators "$num_acc" \
    --hosts "$SSH_HOSTS" \
    --client-host-memory-in-gb "$host_mem" \
    --num-client-hosts 1 \
    --data-dir "$run_data_dir" \
    --results-dir "$RESULTS_ROOT" \
    $OPEN_FLAG --oversubscribe $ALLOW_ROOT \
    $VERBOSITY $STORAGE_FLAG \
    2>&1 | grep "Run the following command" -A1 | tail -1 || true)

  if [ -n "$datagen_cmd" ]; then
    # Replace <INSERT_DATA_DIR> with actual data dir
    datagen_cmd="${datagen_cmd//<INSERT_DATA_DIR>/$run_data_dir}"
    echo "Executing: $datagen_cmd"
    eval "$datagen_cmd" 2>&1 | tail -20
  else
    # Fallback: run datagen directly
    echo "Running datagen directly..."
    mlp training datagen \
      --model "$model" \
      --hosts "$SSH_HOSTS" \
      --num-processes "$num_acc" \
      --data-dir "$run_data_dir" \
      --results-dir "$RESULTS_ROOT" \
      $OPEN_FLAG --oversubscribe $ALLOW_ROOT \
      $VERBOSITY $STORAGE_FLAG 2>&1 | tail -20
  fi

  # Step 3: run benchmark
  echo ""
  echo "--- run ---"
  mlp training run \
    --model "$model" \
    --accelerator-type "$accel" \
    --num-accelerators "$num_acc" \
    --hosts "$SSH_HOSTS" \
    --client-host-memory-in-gb "$host_mem" \
    --num-client-hosts 1 \
    --data-dir "$run_data_dir" \
    --results-dir "$RESULTS_ROOT" \
    $OPEN_FLAG $ALLOW_ROOT --oversubscribe $MPI_SETTINGS \
    $VERBOSITY $STORAGE_FLAG $RUN_EXTRA 2>&1 | tee -a "$RESULTS_ROOT/${model}_run.log"

  echo "--- training $model done ---"
}

# ---- Main ----

DRY_RUN=false
TARGET=""

if [ $# -lt 1 ]; then
  usage
fi

TARGET="$1"
shift
if [ "$1" = "--dry-run" ]; then
  DRY_RUN=true
fi

if [ "$TARGET" = "all" ]; then
  VENDORS=(wd_sn570 biwin_x570 zhitai_ti600 seagate_fc530)
else
  VENDORS=("$TARGET")
fi

check_requirements || exit 1

for vid in "${VENDORS[@]}"; do
  vendor_resolve "$vid" || { echo "SKIP: unknown vendor $vid"; continue; }
  vendor_banner "$vid"

  RESULTS_ROOT="$VENDOR_MOUNT/mlperf_results"
  DATA_DIR="$VENDOR_MOUNT/mlperf_data"

  echo ""
  echo "=== Device: $VENDOR_DEV_NAME ==="
  echo "  Mount:      $VENDOR_MOUNT"
  echo "  Free space: $VENDOR_FREE_GB GiB"
  echo "  Results:    $RESULTS_ROOT"
  echo "  Data dir:   $DATA_DIR"

  if $DRY_RUN; then
    echo ""
    echo "  [DRY RUN] Feasibility (cumulative, sorted smallest-first):"
    dr_remaining="$VENDOR_FREE_GB"
    dr_min_buf=20
    # Checkpointing
    for ckpt in "${CHECKPOINT_MODELS[@]}"; do
      IFS='|' read -r ckpt_model ckpt_np ckpt_gib <<< "$ckpt"
      cost_gib=$((ckpt_gib + 15))
      if [ "$dr_remaining" -ge $((cost_gib + dr_min_buf)) ]; then
        echo "    ✅ Checkpointing $ckpt_model (~${cost_gib}GiB)  [${dr_remaining}GiB → $((dr_remaining - cost_gib))GiB]"
        dr_remaining=$((dr_remaining - cost_gib))
      else
        echo "    ❌ Checkpointing $ckpt_model needs ${cost_gib}GiB, only ${dr_remaining}GiB left"
      fi
    done
    # Training
    for model_def in "${TRAINING_MODELS[@]}"; do
      IFS='|' read -r tr_model tr_accel tr_nacc tr_mem tr_gb <<< "$model_def"
      cost_gib=$((tr_gb + tr_gb / 10 + 10))
      if [ "$dr_remaining" -ge $((cost_gib + dr_min_buf)) ]; then
        echo "    ✅ Training $tr_model (~${cost_gib}GiB)  [${dr_remaining}GiB → $((dr_remaining - cost_gib))GiB]"
        dr_remaining=$((dr_remaining - cost_gib))
      else
        echo "    ❌ Training $tr_model needs ~${cost_gib}GiB, only ${dr_remaining}GiB left"
      fi
    done
    echo ""
    echo "  Estimated final free: ${dr_remaining} GiB (buffer: ${dr_min_buf} GiB)"
    continue
  fi

  # Create dirs
  mkdir -p "$RESULTS_ROOT" "$DATA_DIR"

  # Track cumulative space used across all benchmarks on this disk
  REMAINING_GB="$VENDOR_FREE_GB"
  MIN_BUFFER_GB=20  # keep at least 20 GiB free after all tests

  # ========== CHECKPOINTING ==========
  for ckpt in "${CHECKPOINT_MODELS[@]}"; do
    IFS='|' read -r ckpt_model ckpt_np ckpt_gib <<< "$ckpt"
    cost_gib=$((ckpt_gib + 15))  # dataset + overhead
    if [ "$REMAINING_GB" -lt $((cost_gib + MIN_BUFFER_GB)) ]; then
      echo ""
      echo "⏭️  SKIP checkpointing $ckpt_model: need ${cost_gib}GiB, only ${REMAINING_GB}GiB remaining"
      continue
    fi
    benchmark_checkpointing "$vid" "$ckpt_model" "$ckpt_np" "$ckpt_gib"
    REMAINING_GB=$((REMAINING_GB - cost_gib))
    echo "  → Remaining: ${REMAINING_GB} GiB"
  done

  # ========== TRAINING (sorted by smallest first to maximize coverage) ==========
  # Already sorted: retinanet(80) → flux(80) → cosmoflow(80) → resnet50(160)
  for model_def in "${TRAINING_MODELS[@]}"; do
    IFS='|' read -r tr_model tr_accel tr_nacc tr_mem tr_gb <<< "$model_def"
    # Training needs: dataset (tr_gb) + temp space for generation (~10%) + run overhead
    cost_gib=$((tr_gb + tr_gb / 10 + 10))
    if [ "$REMAINING_GB" -lt $((cost_gib + MIN_BUFFER_GB)) ]; then
      echo ""
      echo "⏭️  SKIP training $tr_model: need ~${cost_gib}GiB (${tr_gb}GiB dataset + overhead), only ${REMAINING_GB}GiB remaining"
      continue
    fi
    benchmark_training "$vid" "$tr_model" "$tr_accel" "$tr_nacc" "$tr_mem" "$tr_gb"
    REMAINING_GB=$((REMAINING_GB - cost_gib))
    echo "  → Remaining: ${REMAINING_GB} GiB"
  done

  # ========== SUMMARY ==========
  echo ""
  echo "================================================================"
  echo "  RESULTS FOR: $vid ($VENDOR_DEV_NAME)"
  echo "  Location: $RESULTS_ROOT"
  echo "================================================================"
  if [ -d "$RESULTS_ROOT" ]; then
    echo ""
    echo "Benchmark run logs:"
    ls -1 "$RESULTS_ROOT"/*.log 2>/dev/null || echo "  (no logs yet)"
    echo ""
    echo "Metadata files:"
    find "$RESULTS_ROOT" -name "*_metadata.json" -type f 2>/dev/null | head -20
    echo ""
    echo "Result directories:"
    ls -d "$RESULTS_ROOT"/*/ 2>/dev/null || echo "  (empty)"
  fi

  # Generate report
  echo ""
  echo "--- Generating report ---"
  mlp reports reportgen --results-dir "$RESULTS_ROOT" \
    $OPEN_FLAG $VERBOSITY 2>&1 | tail -10

done

echo ""
echo "================================================================"
echo "  ALL DONE"
echo "================================================================"
