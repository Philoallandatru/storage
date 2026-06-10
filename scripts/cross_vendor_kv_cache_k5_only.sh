#!/usr/bin/env bash
# cross_vendor_kv_cache_k5_only.sh
# K5 (70B × 4u × 180s) across all 4 disks, serial, full duration.
# Uses v1's proven WORKING parameters: gpu=cpu=0, trace-speedup=1000.
# Result: storage_entries=1695 (Biwin K5 baseline proven).
set -uo pipefail
cd "$(dirname "$0")/.."
PROFILE_DIR="$(pwd)"
export PROFILE_DIR
source scripts/cross_vendor_lib.sh
source "$PROFILE_DIR/.venv/bin/activate"

KV_BENCH_DIR="$PROFILE_DIR/kv_cache_benchmark"
BURST_TRACE="/home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv"
RESULTS_ROOT="$PROFILE_DIR/results/cross_vendor/kv_cache_k5_only"
mkdir -p "$RESULTS_ROOT"

# All 4 disks, in performance order (fastest to slowest to fail fast).
VENDORS=(biwin_x570 seagate_fc530 zhitai_ti600 wd_sn570)

run_k5_on_disk() {
  local vid="$1"
  vendor_resolve "$vid"
  vendor_banner "$vid"

  local cache_dir="$VENDOR_MOUNT/kvcache_k5_$$"
  mkdir -p "$cache_dir"

  local result_dir="$RESULTS_ROOT/${vid}/K5_4u_llama3.1-70b-instruct_180s"
  mkdir -p "$result_dir"
  cd "$result_dir"

  # Clean stale cache dir if any
  rm -rf "$cache_dir"
  mkdir -p "$cache_dir"

  iostat -dx -m 1 > iostat.txt 2>&1 &
  local sampler_pid=$!
  sleep 1

  local start_ts end_ts
  start_ts=$(date +%s)
  echo "  scenario=K5 users=4 model=llama3.1-70b-instruct duration=180s"
  echo "  cache_dir=$cache_dir"
  echo "  started=$(date '+%Y-%m-%d %H:%M:%S')"

  python3 "$KV_BENCH_DIR/kv-cache.py" \
    --config "$KV_BENCH_DIR/config.yaml" \
    --model llama3.1-70b-instruct \
    --num-users 4 \
    --duration 180 \
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
  "scenario": "K5",
  "users": 4,
  "model": "llama3.1-70b-instruct",
  "duration_target_s": 180,
  "duration_actual_s": $elapsed,
  "started": "$start_ts",
  "ended": "$end_ts",
  "tooling": "kv-cache.py v1 K5 params: gpu=cpu=0, speedup=1000"
}
EOF

  rm -rf "$cache_dir"
  cd "$PROFILE_DIR"
  echo "  ✓ $vid K5 done (${elapsed}s) → $result_dir"
}

for vid in "${VENDORS[@]}"; do
  run_k5_on_disk "$vid"
done

echo ""
echo "✅ K5 4-disk sweep complete. Results under $RESULTS_ROOT/"