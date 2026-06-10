#!/usr/bin/env bash
# cross_vendor_kv_pressure.sh
# Cross-vendor KV cache PRESSURE test (v2) — designed to force NVMe spillover.
#
# Key change vs v1: GPU + CPU tiers are SMALL (8 GB each), forcing most KV
# cache accesses to hit NVMe. This is what reveals the storage-tier
# performance differences across disks.
#
# Methodology: BurstGPT trace replay, --trace-speedup 10 (matches prior
# run_70b_users6.sh / run_full_profiling.sh conventions, scaled down by 100x
# from v1's 1000x for realism), tp=8, seed=42.
#
# Test matrix (3 disks serial, no parallelism):
#   P1: 70B × 16u × 5 min   (240 GB working set → mostly NVMe)
#   P2:  8B ×  8u × 10 min  (16-24 GB working set → mostly NVMe)
#
# Estimated wall time: ~50 minutes (15 min for P1 + 30 min for P2 + setup).

set -uo pipefail
cd "$(dirname "$0")/.."
PROFILE_DIR="$(pwd)"
export PROFILE_DIR
source scripts/cross_vendor_lib.sh
# shellcheck source=/dev/null
source "$PROFILE_DIR/.venv/bin/activate"

KV_BENCH_DIR="$PROFILE_DIR/kv_cache_benchmark"
BURST_TRACE="/home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv"
RESULTS_ROOT="$PROFILE_DIR/results/cross_vendor/kv_cache_pressure"
mkdir -p "$RESULTS_ROOT"

VENDORS=(biwin_x570 zhitai_ti600 seagate_fc530)

# Tier capacity (GiB) — small on purpose, force spillover to NVMe.
# 8B model KV ≈ 1-3 GB per user @ 32k ctx
# 70B model KV ≈ 10-30 GB per user @ 32k ctx
# 1+1 GB: only ~10-30% of 70B working set fits in HBM → ~70-90% spillover
# to NVMe where disk differences show up.
GPU_MEM_GB=1
CPU_MEM_GB=1
STORAGE_CAP_GB=400   # generous; we want spillover, not OOM-eviction

declare -A SCEN_USERS=([P1]=16 [P2]=8)
declare -A SCEN_MODEL=([P1]=llama3.1-70b-instruct [P2]=llama3.1-8b)
declare -A SCEN_DURATION=([P1]=300 [P2]=600)

run_scenario_on_disk() {
  local sid="$1" vid="$2"
  local users="${SCEN_USERS[$sid]}"
  local model="${SCEN_MODEL[$sid]}"
  local duration="${SCEN_DURATION[$sid]}"

  vendor_resolve "$vid"
  vendor_banner "$vid"

  local cache_dir="$VENDOR_MOUNT/kvcache_pressure_${sid}_$$"
  mkdir -p "$cache_dir"

  local result_dir="$RESULTS_ROOT/${vid}/${sid}_${users}u_${model}_${duration}s"
  mkdir -p "$result_dir"
  cd "$result_dir"

  iostat -dx -m 1 > iostat.txt 2>&1 &
  local sampler_pid=$!
  sleep 1

  local start_ts end_ts
  start_ts=$(date +%s)
  echo "  scenario=$sid users=$users model=$model duration=${duration}s"
  echo "  tiers: gpu=${GPU_MEM_GB}G cpu=${CPU_MEM_GB}G nvme=∞(cap ${STORAGE_CAP_GB}G)"
  echo "  cache_dir=$cache_dir"
  echo "  started=$(date '+%Y-%m-%d %H:%M:%S')"

  python3 "$KV_BENCH_DIR/kv-cache.py" \
    --config "$KV_BENCH_DIR/config.yaml" \
    --model "$model" \
    --num-users "$users" \
    --duration "$duration" \
    --gpu-mem-gb "$GPU_MEM_GB" \
    --cpu-mem-gb "$CPU_MEM_GB" \
    --num-gpus 8 \
    --tensor-parallel 8 \
    --generation-mode none \
    --use-burst-trace \
    --burst-trace-path "$BURST_TRACE" \
    --trace-speedup 10 \
    --replay-cycles 1 \
    --cache-dir "$cache_dir" \
    --storage-capacity-gb "$STORAGE_CAP_GB" \
    --seed 42 \
    --output "kv_cache_summary.json" \
    --log-level WARNING > kv_cache.log 2>&1 || echo "    ⚠ kv-cache.py returned non-zero"

  end_ts=$(date +%s)
  local elapsed=$((end_ts - start_ts))

  kill $sampler_pid 2>/dev/null || true
  wait $sampler_pid 2>/dev/null || true

  cat > metadata.json <<EOF
{
  "vendor": "$vid",
  "scenario": "$sid",
  "users": $users,
  "model": "$model",
  "duration_target_s": $duration,
  "duration_actual_s": $elapsed,
  "started": "$start_ts",
  "ended": "$end_ts",
  "tier_gpu_gb": $GPU_MEM_GB,
  "tier_cpu_gb": $CPU_MEM_GB,
  "tier_nvme_cap_gb": $STORAGE_CAP_GB,
  "tooling": "kv-cache.py v2 pressure: small tiers (8+8 GB) force NVMe spillover"
}
EOF

  rm -rf "$cache_dir"
  cd "$PROFILE_DIR"
  echo "  ✓ $vid $sid done (${elapsed}s) → $result_dir"
}

run_scenario_all_disks() {
  local sid="$1"
  echo ""
  echo "======================================================"
  echo "  SCENARIO $sid — users=${SCEN_USERS[$sid]} model=${SCEN_MODEL[$sid]} dur=${SCEN_DURATION[$sid]}s"
  echo "======================================================"
  for vid in "${VENDORS[@]}"; do
    run_scenario_on_disk "$sid" "$vid"
  done
}

# Run full matrix P1, P2 (3 disks serial each)
for sid in P1 P2; do
  run_scenario_all_disks "$sid"
done

echo ""
echo "✅ KV cache PRESSURE (v2) complete. Results under $RESULTS_ROOT/"