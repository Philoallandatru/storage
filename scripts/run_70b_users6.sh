#!/usr/bin/env bash
# 70B users=6 BurstGPT run — real-trace mode (fixes missing --use-burst-trace flag
# in the previous run). Fills the missing middle point between users=4 and users=8.
set -euo pipefail

cd ~/llm/storage
# shellcheck disable=SC1091
source .venv/bin/activate

cd kv_cache_benchmark

PROFILE_DIR=/home/ficus/llm/storage/results/kvcache-profile
RUN_ID="burstgpt_70b_tp8_cpu0g_users6_300s_speedup1000_bursttrace_clean_$(date +%Y%m%d_%H%M%S)"
CACHE_DIR="$PROFILE_DIR/kv-cache-dir-$RUN_ID"

mkdir -p "$CACHE_DIR"

python3 kv-cache.py \
  --config config.yaml \
  --model llama3.1-70b-instruct \
  --num-users 6 \
  --duration 300 \
  --gpu-mem-gb 0 \
  --cpu-mem-gb 0 \
  --num-gpus 8 \
  --tensor-parallel 8 \
  --max-concurrent-allocs 2 \
  --generation-mode none \
  --use-burst-trace \
  --burst-trace-path /home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv \
  --trace-speedup 1000 \
  --replay-cycles 0 \
  --cache-dir "$CACHE_DIR" \
  --seed 42 \
  --output "$PROFILE_DIR/test_${RUN_ID}.json" \
  --xlsx-output "$PROFILE_DIR/test_${RUN_ID}.xlsx"

# cleanup the large cache dir, keep only the JSON/XLSX summary
rm -rf "$CACHE_DIR"

echo
echo "=== done: $RUN_ID ==="
echo "JSON : $PROFILE_DIR/test_${RUN_ID}.json"
echo "XLSX : $PROFILE_DIR/test_${RUN_ID}.xlsx"