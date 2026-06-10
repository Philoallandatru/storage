#!/usr/bin/env bash
# cross_vendor_kv_cache_k4_30min_drift.sh
# Per-disk duration K4 GC drift: Biwin/Seagate 1800s, ZhiTai/WD 900s.
# Why: K4 1800s would write ~480 GB; ZhiTai/WD only have 196 GB free.
set -uo pipefail
cd "$(dirname "$0")/.."
PROFILE_DIR="$(pwd)"
export PROFILE_DIR
source scripts/cross_vendor_lib.sh
source "$PROFILE_DIR/.venv/bin/activate"

KV_BENCH_DIR="$PROFILE_DIR/kv_cache_benchmark"
BURST_TRACE="/home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv"
RESULTS_ROOT="$PROFILE_DIR/results/cross_vendor/kv_cache_k4_30min_drift"
mkdir -p "$RESULTS_ROOT"

# Per-disk duration: longer for high-capacity drives, capped for low-capacity.
# K4 at 120s writes ~32 GB → ~0.27 GB/s sustained write rate.
declare -A DUR=(
  [biwin_x570]=1800
  [seagate_fc530]=1800
  [zhitai_ti600]=900
  [wd_sn570]=900
)
VENDORS=(biwin_x570 seagate_fc530 zhitai_ti600 wd_sn570)

run_k4_drift() {
  local vid="$1"
  local dur="${DUR[$vid]}"
  vendor_resolve "$vid"
  vendor_banner "$vid"

  local cache_dir="$VENDOR_MOUNT/kvcache_k4_30m_$$"
  local result_dir="$RESULTS_ROOT/${vid}/K4_16u_llama3.1-8b_${dur}s"
  mkdir -p "$result_dir"
  cd "$result_dir"

  rm -rf "$cache_dir"; mkdir -p "$cache_dir"

  iostat -dx -m 1 > iostat.txt 2>&1 &
  local sampler_pid=$!
  sleep 1

  local start_ts end_ts
  start_ts=$(date +%s)
  echo "  scenario=K4-30M users=16 model=llama3.1-8b duration=${dur}s (disk-specific)"
  echo "  cache_dir=$cache_dir"
  echo "  started=$(date '+%Y-%m-%d %H:%M:%S')"

  python3 "$KV_BENCH_DIR/kv-cache.py" \
    --config "$KV_BENCH_DIR/config.yaml" \
    --model llama3.1-8b \
    --num-users 16 \
    --duration $dur \
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
  "scenario": "K4-30M-DRIFT",
  "users": 16,
  "model": "llama3.1-8b",
  "duration_target_s": $dur,
  "duration_actual_s": $elapsed,
  "started": "$start_ts",
  "ended": "$end_ts",
  "tooling": "kv-cache.py long-steady K4 30-min, gpu=cpu=0, speedup=1000"
}
EOF

  rm -rf "$cache_dir"
  cd "$PROFILE_DIR"
  echo "  ✓ $vid K4-30M done (${elapsed}s) → $result_dir"
}

for vid in "${VENDORS[@]}"; do
  run_k4_drift "$vid"
done

echo ""
echo "✅ K4 30-min drift complete. Results under $RESULTS_ROOT/"