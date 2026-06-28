#!/usr/bin/env bash
# DGX Spark KV cache disk pressure sweep.
#
# Usage:
#   DISK_TARGETS="disk1=/mnt/disk1,disk2=/mnt/disk2" SUITE=realistic bash scripts/dgx_spark_kvcache_sweep.sh
#
# Suites:
#   realistic  DGX Spark-like tiering: GPU/CPU cache enabled, TP1, trace-speedup=10.
#   pure       Pure SSD pressure: gpu=cpu=0, trace-speedup=1000, max-concurrent-allocs=2.
#   long       Long steady-state realistic tiering runs for GC/SLC drift.
#   all        realistic + pure + long.
set -euo pipefail

cd "$(dirname "$0")/.."
PROFILE_DIR="$(pwd)"

KV_BENCH_DIR="${KV_BENCH_DIR:-$PROFILE_DIR/kv_cache_benchmark}"
BURST_TRACE="${BURST_TRACE:-$PROFILE_DIR/datasets/BurstGPT/data/BurstGPT_1.csv}"
RESULTS_ROOT="${RESULTS_ROOT:-$PROFILE_DIR/results/dgx_spark_kvcache/$(date +%Y%m%d_%H%M%S)}"

SUITE="${SUITE:-realistic}"
NUM_GPUS="${NUM_GPUS:-1}"
TENSOR_PARALLEL="${TENSOR_PARALLEL:-1}"

# Interpret 128GB total memory conservatively. Tune these per DGX Spark memory policy.
GPU_MEM_GB="${GPU_MEM_GB:-32}"
CPU_MEM_GB="${CPU_MEM_GB:-32}"
STORAGE_CAPACITY_GB="${STORAGE_CAPACITY_GB:-200}"

DURATION_REALISTIC="${DURATION_REALISTIC:-600}"
DURATION_PURE="${DURATION_PURE:-300}"
DURATION_LONG_8B="${DURATION_LONG_8B:-1800}"
DURATION_LONG_70B="${DURATION_LONG_70B:-1200}"

TRACE_SPEEDUP_REALISTIC="${TRACE_SPEEDUP_REALISTIC:-10}"
TRACE_SPEEDUP_PURE="${TRACE_SPEEDUP_PURE:-1000}"

ENABLE_LATENCY_TRACING="${ENABLE_LATENCY_TRACING:-0}"

if [ -z "${DISK_TARGETS:-}" ]; then
  cat >&2 <<'EOF'
ERROR: DISK_TARGETS is required.

Example:
  DISK_TARGETS="biwin=/mnt/biwin,seagate=/mnt/seagate" \
    SUITE=realistic \
    GPU_MEM_GB=32 CPU_MEM_GB=32 \
    bash scripts/dgx_spark_kvcache_sweep.sh
EOF
  exit 2
fi

if [ ! -f "$BURST_TRACE" ]; then
  echo "ERROR: BurstGPT trace not found: $BURST_TRACE" >&2
  exit 2
fi

if [ -f "$PROFILE_DIR/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$PROFILE_DIR/.venv/bin/activate"
fi

mkdir -p "$RESULTS_ROOT"

declare -a DISK_LABELS=()
declare -a DISK_MOUNTS=()

parse_disk_targets() {
  local item label mount
  IFS=',' read -r -a entries <<< "$DISK_TARGETS"
  for item in "${entries[@]}"; do
    label="${item%%=*}"
    mount="${item#*=}"
    if [ -z "$label" ] || [ -z "$mount" ] || [ "$label" = "$mount" ]; then
      echo "ERROR: invalid DISK_TARGETS entry: $item" >&2
      exit 2
    fi
    if [ ! -d "$mount" ]; then
      echo "ERROR: mount path does not exist for $label: $mount" >&2
      exit 2
    fi
    DISK_LABELS+=("$label")
    DISK_MOUNTS+=("$mount")
  done
}

run_kvcache() {
  local disk_label="$1"
  local disk_mount="$2"
  local scenario="$3"
  local model="$4"
  local users="$5"
  local duration="$6"
  local gpu_mem="$7"
  local cpu_mem="$8"
  local trace_speedup="$9"
  local replay_cycles="${10}"
  local max_concurrent="${11}"

  local result_dir="$RESULTS_ROOT/$disk_label/$scenario"
  local cache_dir="$disk_mount/dgx_spark_kvcache_${scenario}_$$"
  mkdir -p "$result_dir"
  rm -rf "$cache_dir"
  mkdir -p "$cache_dir"

  echo ""
  echo "============================================================"
  echo "disk=$disk_label mount=$disk_mount scenario=$scenario"
  echo "model=$model users=$users duration=${duration}s gpu=${gpu_mem}GB cpu=${cpu_mem}GB tp=$TENSOR_PARALLEL"
  echo "results=$result_dir"
  echo "============================================================"

  (
    cd "$result_dir"

    iostat -dx -m 1 > iostat.txt 2>&1 &
    local iostat_pid=$!
    sleep 1

    local start_ts end_ts rc
    start_ts="$(date +%s)"

    local -a args=(
      "$KV_BENCH_DIR/kv-cache.py"
      --config "$KV_BENCH_DIR/config.yaml"
      --model "$model"
      --num-users "$users"
      --duration "$duration"
      --gpu-mem-gb "$gpu_mem"
      --cpu-mem-gb "$cpu_mem"
      --num-gpus "$NUM_GPUS"
      --tensor-parallel "$TENSOR_PARALLEL"
      --generation-mode none
      --use-burst-trace
      --burst-trace-path "$BURST_TRACE"
      --trace-speedup "$trace_speedup"
      --replay-cycles "$replay_cycles"
      --storage-capacity-gb "$STORAGE_CAPACITY_GB"
      --cache-dir "$cache_dir"
      --seed 42
      --output kv_cache_summary.json
      --xlsx-output kv_cache_summary.xlsx
      --log-level WARNING
    )

    if [ "$max_concurrent" != "none" ]; then
      args+=(--max-concurrent-allocs "$max_concurrent")
    fi
    if [ "$ENABLE_LATENCY_TRACING" = "1" ]; then
      args+=(--enable-latency-tracing)
    fi

    set +e
    python3 "${args[@]}" > kv_cache.log 2>&1
    rc=$?
    set -e

    end_ts="$(date +%s)"

    kill "$iostat_pid" 2>/dev/null || true
    wait "$iostat_pid" 2>/dev/null || true

    cat > metadata.json <<EOF
{
  "disk_label": "$disk_label",
  "disk_mount": "$disk_mount",
  "scenario": "$scenario",
  "model": "$model",
  "users": $users,
  "duration_target_s": $duration,
  "duration_actual_s": $((end_ts - start_ts)),
  "gpu_mem_gb": $gpu_mem,
  "cpu_mem_gb": $cpu_mem,
  "num_gpus": $NUM_GPUS,
  "tensor_parallel": $TENSOR_PARALLEL,
  "trace_speedup": $trace_speedup,
  "replay_cycles": $replay_cycles,
  "storage_capacity_gb": $STORAGE_CAPACITY_GB,
  "max_concurrent_allocs": "$max_concurrent",
  "enable_latency_tracing": "$ENABLE_LATENCY_TRACING",
  "exit_code": $rc,
  "started_epoch_s": "$start_ts",
  "ended_epoch_s": "$end_ts"
}
EOF

    rm -rf "$cache_dir"

    if [ "$rc" -ne 0 ]; then
      echo "WARN: kv-cache.py exited with rc=$rc for $disk_label/$scenario"
    fi
  )
}

run_realistic_suite() {
  local label mount idx user
  for idx in "${!DISK_LABELS[@]}"; do
    label="${DISK_LABELS[$idx]}"
    mount="${DISK_MOUNTS[$idx]}"

    for user in 1 2 4 8; do
      run_kvcache "$label" "$mount" "realistic_70b_u${user}_${DURATION_REALISTIC}s" \
        "llama3.1-70b-instruct" "$user" "$DURATION_REALISTIC" \
        "$GPU_MEM_GB" "$CPU_MEM_GB" "$TRACE_SPEEDUP_REALISTIC" 1 "none"
    done

    for user in 8 16 32; do
      run_kvcache "$label" "$mount" "realistic_8b_u${user}_${DURATION_REALISTIC}s" \
        "llama3.1-8b" "$user" "$DURATION_REALISTIC" \
        "$GPU_MEM_GB" "$CPU_MEM_GB" "$TRACE_SPEEDUP_REALISTIC" 1 "none"
    done
  done
}

run_pure_suite() {
  local label mount idx
  for idx in "${!DISK_LABELS[@]}"; do
    label="${DISK_LABELS[$idx]}"
    mount="${DISK_MOUNTS[$idx]}"

    run_kvcache "$label" "$mount" "pure_70b_u4_${DURATION_PURE}s" \
      "llama3.1-70b-instruct" 4 "$DURATION_PURE" \
      0 0 "$TRACE_SPEEDUP_PURE" 0 2

    run_kvcache "$label" "$mount" "pure_8b_u16_${DURATION_PURE}s" \
      "llama3.1-8b" 16 "$DURATION_PURE" \
      0 0 "$TRACE_SPEEDUP_PURE" 0 2
  done
}

run_long_suite() {
  local label mount idx
  for idx in "${!DISK_LABELS[@]}"; do
    label="${DISK_LABELS[$idx]}"
    mount="${DISK_MOUNTS[$idx]}"

    run_kvcache "$label" "$mount" "long_8b_u16_${DURATION_LONG_8B}s" \
      "llama3.1-8b" 16 "$DURATION_LONG_8B" \
      "$GPU_MEM_GB" "$CPU_MEM_GB" "$TRACE_SPEEDUP_REALISTIC" 1 "none"

    run_kvcache "$label" "$mount" "long_70b_u4_${DURATION_LONG_70B}s" \
      "llama3.1-70b-instruct" 4 "$DURATION_LONG_70B" \
      "$GPU_MEM_GB" "$CPU_MEM_GB" "$TRACE_SPEEDUP_REALISTIC" 1 "none"
  done
}

parse_disk_targets

cat > "$RESULTS_ROOT/run_config.txt" <<EOF
DISK_TARGETS=$DISK_TARGETS
SUITE=$SUITE
NUM_GPUS=$NUM_GPUS
TENSOR_PARALLEL=$TENSOR_PARALLEL
GPU_MEM_GB=$GPU_MEM_GB
CPU_MEM_GB=$CPU_MEM_GB
STORAGE_CAPACITY_GB=$STORAGE_CAPACITY_GB
DURATION_REALISTIC=$DURATION_REALISTIC
DURATION_PURE=$DURATION_PURE
DURATION_LONG_8B=$DURATION_LONG_8B
DURATION_LONG_70B=$DURATION_LONG_70B
TRACE_SPEEDUP_REALISTIC=$TRACE_SPEEDUP_REALISTIC
TRACE_SPEEDUP_PURE=$TRACE_SPEEDUP_PURE
ENABLE_LATENCY_TRACING=$ENABLE_LATENCY_TRACING
EOF

case "$SUITE" in
  realistic)
    run_realistic_suite
    ;;
  pure)
    run_pure_suite
    ;;
  long)
    run_long_suite
    ;;
  all)
    run_realistic_suite
    run_pure_suite
    run_long_suite
    ;;
  *)
    echo "ERROR: unknown SUITE=$SUITE (expected realistic, pure, long, all)" >&2
    exit 2
    ;;
esac

echo ""
echo "DGX Spark KV cache sweep complete: $RESULTS_ROOT"
