#!/usr/bin/env bash
# cross_vendor_kv_cache_pressure.sh
# Pressure-test variants of the KV cache benchmark — fixes the v1 P0 issues
# (see docs/kv-cache-test-evaluation-2026-06-10.md) and pushes the workloads
# to amplify per-disk differences.
#
# Methodology inherits from scripts/run_70b_users6.sh + scripts/cross_vendor_kv_cache.sh,
# but applies the v1 P0 fixes:
#   - --gpu-mem-gb 80 --cpu-mem-gb 80      (real tier cascade, not pure NVMe)
#   - --trace-speedup 10                   (was 1000, compressed 33h trace)
#   - --max-concurrent-allocs removed       (was 2, suppressed real concurrency)
#   - --storage-capacity-gb 200            (bound the cache dir)
#
# Three disks only (skip WD — already validated as the slowest in v1):
#   biwin_x570 / zhitai_ti600 / seagate_fc530
#
# Scenarios (run in this order):
#   P1: 70B / 16u / 300s  — large model + high concurrency (amplifies write
#       tail difference seen in v1 K5: Biwin 28 ms vs ZhiTai 1073 ms P99)
#   P2: 8u-8B / 600s     — long-duration high concurrency (engages GC; Biwin
#       shows -30% drift per T4 over 15 min)
#
# Total estimated wall time: ~50 min (3 disks × 2 scenarios serial).

set -uo pipefail
cd "$(dirname "$0")/.."
PROFILE_DIR="$(pwd)"
export PROFILE_DIR
source scripts/cross_vendor_lib.sh
source "$PROFILE_DIR/.venv/bin/activate"

# Three disks only — skip WD per v1 conclusion
VENDORS=(biwin_x570 zhitai_ti600 seagate_fc530)

KV_BENCH_DIR="$PROFILE_DIR/kv_cache_benchmark"
BURST_TRACE="/home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv"
RESULTS_ROOT="$PROFILE_DIR/results/cross_vendor/kv_cache_pressure"
mkdir -p "$RESULTS_ROOT"

# Scenario P1: 70B / 16 user / 300s — push the write-path stress
# Scenario P2: 8u-8B / 600s — long-duration high concurrency (GC engagement)
declare -A SCEN_USERS=([P1]=16 [P2]=8)
declare -A SCEN_MODEL=([P1]=llama3.1-70b-instruct [P2]=llama3.1-8b)
declare -A SCEN_DURATION=([P1]=300 [P2]=600)

# Shared parameters (the v1 P0 fixes)
SHARED_ARGS=(
  --config "$KV_BENCH_DIR/config.yaml"
  --gpu-mem-gb 80
  --cpu-mem-gb 80
  --num-gpus 8
  --tensor-parallel 8
  --generation-mode none
  --use-burst-trace
  --burst-trace-path "$BURST_TRACE"
  --trace-speedup 10          # v1 used 1000 — too compressed
  --replay-cycles 1           # 1 full replay per run
  --storage-capacity-gb 200   # bound the cache dir
  --seed 42
  --log-level WARNING
)

run_scenario_on_disk() {
  local sid="$1" vid="$2"
  local users="${SCEN_USERS[$sid]}"
  local model="${SCEN_MODEL[$sid]}"
  local duration="${SCEN_DURATION[$sid]}"

  vendor_resolve "$vid"
  vendor_banner "$vid"

  local cache_dir="$VENDOR_MOUNT/kvcache_press_${sid}_$$"
  mkdir -p "$cache_dir"

  local result_dir="$RESULTS_ROOT/${vid}/${sid}_${users}u_${model}_${duration}s"
  mkdir -p "$result_dir"
  cd "$result_dir"

  # Background iostat sampler (1 Hz, matches prior methodology)
  iostat -dx -m 1 > iostat.txt 2>&1 &
  local sampler_pid=$!
  sleep 1

  local start_ts end_ts
  start_ts=$(date +%s)
  echo "  scenario=$sid users=$users model=$model duration=${duration}s"
  echo "  cache_dir=$cache_dir"
  echo "  started=$(date '+%Y-%m-%d %H:%M:%S')"

  # NOTE: no --max-concurrent-allocs cap (v1 P0 #3 fix).
  # All other shared args come from SHARED_ARGS.
  python3 "$KV_BENCH_DIR/kv-cache.py" \
    "${SHARED_ARGS[@]}" \
    --model "$model" \
    --num-users "$users" \
    --duration "$duration" \
    --cache-dir "$cache_dir" \
    --output "kv_cache_summary.json" > kv_cache.log 2>&1 \
    || echo "    ⚠ kv-cache.py returned non-zero"

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
  "tooling": "kv-cache.py BurstGPT pressure test (v1 P0 fixes applied)",
  "v1_fixes": {
    "gpu_mem_gb": 80,
    "cpu_mem_gb": 80,
    "trace_speedup": 10,
    "max_concurrent_allocs": "uncapped",
    "storage_capacity_gb": 200
  }
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
  echo "  PRESSURE SCENARIO $sid — users=${SCEN_USERS[$sid]} model=${SCEN_MODEL[$sid]} dur=${SCEN_DURATION[$sid]}s"
  echo "======================================================"
  for vid in "${VENDORS[@]}"; do
    run_scenario_on_disk "$sid" "$vid"
  done
}

# Run P1 then P2
for sid in P1 P2; do
  run_scenario_all_disks "$sid"
done

echo ""
echo "✅ KV cache pressure test complete. Results under $RESULTS_ROOT/"