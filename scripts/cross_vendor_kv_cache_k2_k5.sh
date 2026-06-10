#!/usr/bin/env bash
# Run only K2-K5 across all 4 disks (K1 already done in prior smoke run).
# Same methodology, same per-disk serial order.

set -uo pipefail
cd "$(dirname "$0")/.."
PROFILE_DIR="$(pwd)"
export PROFILE_DIR
source scripts/cross_vendor_lib.sh
source "$PROFILE_DIR/.venv/bin/activate"

# Override VENDORS to skip WD (already have K1), then run K2-K5 on all 4 disks.
VENDORS=(wd_sn570 biwin_x570 zhitai_ti600 seagate_fc530)

KV_BENCH_DIR="$PROFILE_DIR/kv_cache_benchmark"
BURST_TRACE="/home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv"
RESULTS_ROOT="$PROFILE_DIR/results/cross_vendor/kv_cache"
mkdir -p "$RESULTS_ROOT"

declare -A SCEN_USERS=([K2]=4  [K3]=8   [K4]=16 [K5]=4)
declare -A SCEN_MODEL=([K2]=llama3.1-8b [K3]=llama3.1-8b [K4]=llama3.1-8b [K5]=llama3.1-70b-instruct)
declare -A SCEN_DURATION=([K2]=120 [K3]=120 [K4]=120 [K5]=180)

run_scenario_on_disk() {
  local sid="$1" vid="$2"
  local users="${SCEN_USERS[$sid]}"
  local model="${SCEN_MODEL[$sid]}"
  local duration="${SCEN_DURATION[$sid]}"

  vendor_resolve "$vid"
  vendor_banner "$vid"

  local cache_dir="$VENDOR_MOUNT/kvcache_test_${sid}_$$"
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
  echo "  cache_dir=$cache_dir"
  echo "  started=$(date '+%Y-%m-%d %H:%M:%S')"

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
  "cache_dir": "$cache_dir",
  "host_dram_total_gb": $(awk '/MemTotal/ {print int($2/1024/1024)}' /proc/meminfo),
  "tooling": "kv-cache.py BurstGPT trace replay, gpu_mem=cpu_mem=0 (pure NVMe), tp=8"
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

# Run K2, K3, K4, K5 (K1 already done in smoke run)
for sid in K2 K3 K4 K5; do
  run_scenario_all_disks "$sid"
done

echo ""
echo "✅ K2-K5 complete. Results under $RESULTS_ROOT/"