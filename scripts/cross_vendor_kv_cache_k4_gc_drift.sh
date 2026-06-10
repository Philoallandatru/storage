#!/usr/bin/env bash
# cross_vendor_kv_cache_k4_gc_drift.sh
# K4 GC-drift long-steady-state: 8B x 16u x 1200s per disk, 4 disks serial.
# Designed to expose SLC cache exhaustion / GC cliffs on QLC consumer drives.
#
# Estimated disk usage: 1200/120 * 31.8 GB write ≈ 318 GB per disk.
# WD/ZhiTai have ~196 GB free → 1200s is conservative upper bound.
set -uo pipefail
cd "$(dirname "$0")/.."
PROFILE_DIR="$(pwd)"
export PROFILE_DIR
source scripts/cross_vendor_lib.sh
source "$PROFILE_DIR/.venv/bin/activate"

DURATION=${DURATION:-1200}   # 20 min per disk
KV_BENCH_DIR="$PROFILE_DIR/kv_cache_benchmark"
BURST_TRACE="/home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv"
RESULTS_ROOT="$PROFILE_DIR/results/cross_vendor/kv_cache_k4_gc_drift"
mkdir -p "$RESULTS_ROOT"

VENDORS=(biwin_x570 seagate_fc530 zhitai_ti600 wd_sn570)

run_k4_gc_drift() {
  local vid="$1"
  vendor_resolve "$vid"
  vendor_banner "$vid"

  local cache_dir="$VENDOR_MOUNT/kvcache_k4_gc_$$"
  local result_dir="$RESULTS_ROOT/${vid}/K4_16u_llama3.1-8b_${DURATION}s"
  mkdir -p "$result_dir"
  cd "$result_dir"

  rm -rf "$cache_dir"; mkdir -p "$cache_dir"

  iostat -dx -m 1 > iostat.txt 2>&1 &
  local sampler_pid=$!
  sleep 1

  local start_ts end_ts
  start_ts=$(date +%s)
  echo "  scenario=K4-GC users=16 model=llama3.1-8b duration=${DURATION}s"
  echo "  cache_dir=$cache_dir"
  echo "  started=$(date '+%Y-%m-%d %H:%M:%S')"

  python3 "$KV_BENCH_DIR/kv-cache.py" \
    --config "$KV_BENCH_DIR/config.yaml" \
    --model llama3.1-8b \
    --num-users 16 \
    --duration $DURATION \
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
    --output kv_cache_summary.json \
    --log-level WARNING > kv_cache.log 2>&1 || echo "    ⚠ kv-cache.py returned non-zero"

  end_ts=$(date +%s)
  local elapsed=$((end_ts - start_ts))

  kill $sampler_pid 2>/dev/null || true
  wait $sampler_pid 2>/dev/null || true

  cat > metadata.json <<EOF
{
  "vendor": "$vid",
  "scenario": "K4-GC-DRIFT",
  "users": 16,
  "model": "llama3.1-8b",
  "duration_target_s": $DURATION,
  "duration_actual_s": $elapsed,
  "started": "$start_ts",
  "ended": "$end_ts",
  "tooling": "kv-cache.py long-steady K4 GC drift, gpu=cpu=0, speedup=1000"
}
EOF

  rm -rf "$cache_dir"
  cd "$PROFILE_DIR"
  echo "  ✓ $vid K4-GC done (${elapsed}s) → $result_dir"
}

for vid in "${VENDORS[@]}"; do
  run_k4_gc_drift "$vid"
done

echo ""
echo "✅ K4 GC-drift 4-disk sweep complete. Results under $RESULTS_ROOT/"