#!/usr/bin/env bash
# Long steady-state run — KV-Cache 70B users=6 for 30 minutes
#
# Goals:
#   - Observe GC drift over a 30-min real-I/O run
#   - Capture long-term SLC cache behavior under real workload
#   - Produce time-series iostat data for trend analysis
#
# IMPORTANT: uses Round 2 mode (no --io-trace-log) so that real hardware
# I/O happens and iostat sees actual SSD pressure. Without this, NullBackend
# would absorb all I/O and iostat would always read 0.00.
#
# Compared to run_full_profiling.sh:
#   - Single round only (real I/O mode, no need for trace + hwio duplication)
#   - Longer duration (30 min default, configurable)
#   - Higher-resolution iostat (per-second)

set -euo pipefail

DURATION_MINUTES="${1:-30}"
DURATION=$((DURATION_MINUTES * 60))

PROFILE_DIR="/home/ficus/llm/storage/results/kvcache-profile"
TS="$(date +%Y%m%d_%H%M%S)"
RUN_ID="long_steady_state_${DURATION_MINUTES}min_${TS}"
LOG_DIR="${PROFILE_DIR}/profiling/${RUN_ID}"
CACHE_DIR="${PROFILE_DIR}/kv-cache-dir-${RUN_ID}"
mkdir -p "${LOG_DIR}"

echo "==================================================="
echo "Long steady-state run (real I/O mode): ${RUN_ID}"
echo "  duration: ${DURATION_MINUTES} min (${DURATION}s)"
echo "  model: llama3.1-70b-instruct, users: 6"
echo "  log dir: ${LOG_DIR}"
echo "==================================================="

cd ~/llm/storage/kv_cache_benchmark
source ../.venv/bin/activate

# L1 device profiler — iostat + pidstat
iostat -dx -m 1 > "${LOG_DIR}/iostat.log" 2>&1 &
IOSTAT_PID=$!
pidstat -d -r -s -u 1 > "${LOG_DIR}/pidstat.log" 2>&1 &
PIDSTAT_PID=$!

cleanup() {
    echo "[cleanup] killing background profilers"
    kill $IOSTAT_PID $PIDSTAT_PID 2>/dev/null || true
    rm -rf "${CACHE_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

echo "Started L1 device profilers: iostat=$IOSTAT_PID pidstat=$PIDSTAT_PID"

# Real I/O mode (no --io-trace-log so writes actually hit SSD)
BENCH_OUT="${PROFILE_DIR}/test_${RUN_ID}.json"
BENCH_XLSX="${PROFILE_DIR}/test_${RUN_ID}.xlsx"

START=$(date +%s)
python3 kv-cache.py --config config.yaml \
    --model "llama3.1-70b-instruct" \
    --num-users "6" \
    --duration "${DURATION}" \
    --gpu-mem-gb 0 --cpu-mem-gb 0 \
    --num-gpus 8 --tensor-parallel 8 \
    --max-concurrent-allocs 2 \
    --generation-mode none \
    --use-burst-trace \
    --burst-trace-path /home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv \
    --trace-speedup 1000 \
    --replay-cycles 0 \
    --cache-dir "${CACHE_DIR}" \
    --seed 42 \
    --enable-latency-tracing \
    --enable-autoscaling \
    --log-level INFO \
    --output "${BENCH_OUT}" \
    --xlsx-output "${BENCH_XLSX}" \
    2>&1 | tee "${LOG_DIR}/bench.log"
END=$(date +%s)

echo ""
echo "==================================================="
echo "✓ Long steady-state run complete: ${RUN_ID}"
echo "  actual runtime: $((END - START))s (expected ${DURATION}s)"
echo "  json:  ${BENCH_OUT}"
echo "  iostat: ${LOG_DIR}/iostat.log"
echo "  pidstat: ${LOG_DIR}/pidstat.log"
echo "==================================================="