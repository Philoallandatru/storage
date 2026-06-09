#!/usr/bin/env bash
# cross_vendor_kv_cache.sh
# Cross-vendor KV cache benchmark runner (kv-cache.py) — 4 disks × 5 scenarios.
#
# Reference: scripts/run_70b_users6.sh + scripts/run_full_profiling.sh
# Uses BurstGPT trace replay with --gpu-mem-gb 0 --cpu-mem-gb 0 (pure NVMe
# tier benchmark, matching the methodology used in the previous BurstGPT runs).
#
# Usage: bash scripts/cross_vendor_kv_cache.sh [SCENARIO_ID]
#   If SCENARIO_ID given (e.g. K2), runs only that scenario across all 4 disks.
#   If empty, runs the full K1..K5 matrix in serial.
#
# Each run:
#   - iostat -dx -m 1 in background (KV cache tier only, no GPU/CPU tier)
#   - Runs kv-cache.py with BurstGPT trace replay, tp=8, seed=42
#   - Saves run_summary.json + iostat.txt + metadata.json
#   - Cleans cache dir after each run
#
# Estimated wall time: ~1.5–2 hours for full K1..K5 matrix (5min/run + setup).

set -uo pipefail
cd "$(dirname "$0")/.."
PROFILE_DIR="$(pwd)"
export PROFILE_DIR
source scripts/cross_vendor_lib.sh

# Activate Python venv
# shellcheck source=/dev/null
source "$PROFILE_DIR/.venv/bin/activate"

KV_BENCH_DIR="$PROFILE_DIR/kv_cache_benchmark"
BURST_TRACE="/home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv"
RESULTS_ROOT="$PROFILE_DIR/results/cross_vendor/kv_cache"
mkdir -p "$RESULTS_ROOT"

VENDORS=(wd_sn570 biwin_x570 zhitai_ti600 seagate_fc530)

# Reduced intensity scenarios — match the existing run_70b_users6.sh / run_full_profiling.sh
# methodology (tp=8, gpu_mem=0, cpu_mem=0, burst trace, trace-speedup 1000).
#
#   K1:  1 user,  8B model, 120s — single-user latency floor
#   K2:  4 user,  8B model, 120s — typical inference service
#   K3:  8 user,  8B model, 120s — high concurrency
#   K4: 16 user,  8B model, 120s — saturation probe
#   K5:  4 user, 70B model, 180s — large KV cache (longer to let burst fill)
#
# Wall time per scenario per disk = duration + ~5s setup + ~5s cleanup.
# Total: 5 scenarios × 4 disks × ~130s avg ≈ 45 min real time (parallel-safe
# if needed, but we run serial to keep storage I/O clean).
declare -A SCEN_USERS=([K1]=1   [K2]=4  [K3]=8   [K4]=16 [K5]=4)
declare -A SCEN_MODEL=([K1]=llama3.1-8b [K2]=llama3.1-8b [K3]=llama3.1-8b [K4]=llama3.1-8b [K5]=llama3.1-70b-instruct)
declare -A SCEN_DURATION=([K1]=120 [K2]=120 [K3]=120 [K4]=120 [K5]=180)

run_scenario_on_disk() {
  local sid="$1" vid="$2"
  local users="${SCEN_USERS[$sid]}"
  local model="${SCEN_MODEL[$sid]}"
  local duration="${SCEN_DURATION[$sid]}"

  vendor_resolve "$vid"
  vendor_banner "$vid"

  # Per-run cache dir (cleaned up after)
  local cache_dir="$VENDOR_MOUNT/kvcache_test_${sid}_$$"
  mkdir -p "$cache_dir"

  local result_dir="$RESULTS_ROOT/${vid}/${sid}_${users}u_${model}_${duration}s"
  mkdir -p "$result_dir"
  cd "$result_dir"

  # Background iostat sampler (matches the methodology used in T1–T4)
  iostat -dx -m 1 > iostat.txt 2>&1 &
  local sampler_pid=$!
  sleep 1

  local start_ts end_ts
  start_ts=$(date +%s)

  echo "  scenario=$sid users=$users model=$model duration=${duration}s"
  echo "  cache_dir=$cache_dir"
  echo "  started=$(date '+%Y-%m-%d %H:%M:%S')"

  # kv-cache.py invocation: mirrors run_70b_users6.sh / run_full_profiling.sh
  #   --gpu-mem-gb 0 --cpu-mem-gb 0      → pure NVMe tier (matches prior methodology)
  #   --num-gpus 8 --tensor-parallel 8   → 8-GPU TP=8 server deployment (server-class)
  #   --max-concurrent-allocs 2          → limit concurrency (per existing script)
  #   --use-burst-trace                  → realistic Azure BurstGPT trace
  #   --trace-speedup 1000               → compress wall time (matches prior)
  #   --replay-cycles 0                  → single replay
  #   --generation-mode none             → no GPU sim, isolates storage I/O
  python3 "$KV_BENCH_DIR/kv-cache.py" \
    --config "$KV_BENCH_DIR/config.yaml" \
    --model "$model" \
    --num-users "$users" \
    --duration "$duration" \
    --gpu-mem-gb 0 \
    --cpu-mem-gb 0 \
    --num-gpus 8 \
    --tensor-parallel 8 \
    --max-concurrent-allocs 2 \
    --generation-mode none \
    --use-burst-trace \
    --burst-trace-path "$BURST_TRACE" \
    --trace-speedup 1000 \
    --replay-cycles 0 \
    --cache-dir "$cache_dir" \
    --seed 42 \
    --output "kv_cache_summary.json" \
    --log-level WARNING > kv_cache.log 2>&1 || echo "    ⚠ kv-cache.py returned non-zero"

  end_ts=$(date +%s)
  local elapsed=$((end_ts - start_ts))

  # Stop iostat sampler
  kill $sampler_pid 2>/dev/null || true
  wait $sampler_pid 2>/dev/null || true

  # Persist run metadata
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
  "cache_dir": "$cache_dir",
  "host_dram_total_gb": $(awk '/MemTotal/ {print int($2/1024/1024)}' /proc/meminfo),
  "tooling": "kv-cache.py BurstGPT trace replay, gpu_mem=cpu_mem=0 (pure NVMe), tp=8"
}
EOF

  # Cleanup the cache dir (we already have iostat + JSON summary)
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

# === Entry point ===
if [ "${1:-}" != "" ]; then
  run_scenario_all_disks "$1"
else
  for sid in K1 K2 K3 K4 K5; do
    run_scenario_all_disks "$sid"
  done
fi

echo ""
echo "✅ KV cache cross-vendor complete. Results under $RESULTS_ROOT/"