#!/bin/bash
# run_prefill_decode_sweep.sh — 跑 prefill-only / decode-only profile (顺序跑以避免 bpftrace 互相干扰)
#
# 用法: bash scripts/run_prefill_decode_sweep.sh
# 设计:
#   - 不开 --enable-autoscaling (避免 autoscaling 把 user count 涨到 500+)
#   - 同时开 --io-trace-log + --enable-latency-tracing (bpftrace)
#   - 同时开 iostat + pidstat (后台)
#   - perf 单独跑 (因为 perf_event_paranoid=-1 已生效)
#
# 注意:prefill/decode-only 顺序跑(不并行),原因:
#   - 两个 bpftrace 同时跑会抢 CPU + dmesg 噪音
#   - 每个 bpftrace 自己占 1 个进程 + 16 个 tracepoint
#   - iostat 同时跑可能混淆哪个数据来自哪个 run
#   - 串行跑 ~12 分钟 (300s trace + 300s hwio + overhead)

set -euo pipefail

# === 配置 ===
MODEL="llama3.1-70b-instruct"
USERS=6
DURATION=300
PROFILE_DIR="/home/ficus/llm/storage/results/kvcache-profile"
TS="$(date +%Y%m%d_%H%M%S)"

# prefilled 与 KV cache 在 decode 阶段访问
# prefill-only: write-heavy, no decode reads
# decode-only: read-heavy, assumes KV exists

run_one_phase() {
    local phase_name="$1"
    local flag="$2"
    local RUN_ID="burstgpt_70b_users6_${phase_name}_${TS}"
    local LOG_DIR="${PROFILE_DIR}/profiling/${RUN_ID}"
    local CACHE_DIR="${PROFILE_DIR}/kv-cache-dir-${RUN_ID}"
    mkdir -p "${LOG_DIR}"

    echo ""
    echo "==================================================="
    echo "▶ ${phase_name}: 70B users=6 --${flag}"
    echo "  run_id: ${RUN_ID}"
    echo "  log_dir: ${LOG_DIR}"
    echo "==================================================="

    # ── L1 device profilers (后台) ──
    iostat -dx -m 1 > "${LOG_DIR}/iostat.log" 2>&1 &
    IOSTAT_PID=$!
    pidstat -d -r -s -u 1 > "${LOG_DIR}/pidstat.log" 2>&1 &
    PIDSTAT_PID=$!
    sudo -n perf stat -e cache-misses,cache-references,cs,migrations,page-faults \
        sleep "${DURATION}" > "${LOG_DIR}/perf.log" 2>&1 &
    PERF_PID=$!

    cleanup() {
        kill $IOSTAT_PID $PIDSTAT_PID $PERF_PID 2>/dev/null || true
        rm -rf "${CACHE_DIR}" 2>/dev/null || true
    }
    trap cleanup EXIT

    cd ~/llm/storage/kv_cache_benchmark
    source ../.venv/bin/activate

    # ── Run KV cache benchmark (Round 1 = trace, Round 2 = hwio + bpftrace) ──
    echo ""
    echo "  [round 1] trace mode (--io-trace-log)"
    python3 kv-cache.py --config config.yaml \
        --model "${MODEL}" \
        --num-users "${USERS}" \
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
        --io-trace-log "${LOG_DIR}/kv_trace.csv.zst" \
        --"${flag}" \
        --log-level INFO \
        --output "${PROFILE_DIR}/test_${RUN_ID}_trace.json" \
        --xlsx-output "${PROFILE_DIR}/test_${RUN_ID}_trace.xlsx" \
        2>&1 | tee "${LOG_DIR}/round1_bench.log"

    echo ""
    echo "  [round 2] hardware I/O + bpftrace (--enable-latency-tracing)"
    CACHE_DIR2="${PROFILE_DIR}/kv-cache-dir-${RUN_ID}_hwio"
    mkdir -p "${CACHE_DIR2}"

    python3 kv-cache.py --config config.yaml \
        --model "${MODEL}" \
        --num-users "${USERS}" \
        --duration "${DURATION}" \
        --gpu-mem-gb 0 --cpu-mem-gb 0 \
        --num-gpus 8 --tensor-parallel 8 \
        --max-concurrent-allocs 2 \
        --generation-mode none \
        --use-burst-trace \
        --burst-trace-path /home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv \
        --trace-speedup 1000 \
        --replay-cycles 0 \
        --cache-dir "${CACHE_DIR2}" \
        --seed 42 \
        --enable-latency-tracing \
        --"${flag}" \
        --log-level INFO \
        --output "${PROFILE_DIR}/test_${RUN_ID}_hwio.json" \
        --xlsx-output "${PROFILE_DIR}/test_${RUN_ID}_hwio.xlsx" \
        2>&1 | tee "${LOG_DIR}/round2_bench.log"

    rm -rf "${CACHE_DIR2}" 2>/dev/null || true
    echo ""
    echo "✓ ${phase_name} 完成: ${RUN_ID}"
    ls -la "${LOG_DIR}/" 2>&1 | head -10
}

# === 跑 prefill-only + decode-only (顺序,因为可能想用同一 iostat session) ===
# 实际并行跑:用 -- 分割
echo "Starting prefill-only + decode-only sweep at $(date)"

# 第一个跑完再跑第二个(避免两个 bpftrace + iostat 互相干扰)
run_one_phase "prefill_only" "prefill-only"
run_one_phase "decode_only" "decode-only"

echo ""
echo "==================================================="
echo "✓ ALL DONE: prefill/decode sweep"
echo "==================================================="