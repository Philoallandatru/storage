#!/bin/bash
# run_full_profiling.sh — 同时开 4 层 profiling 跑 KV-Cache benchmark
#
# 用法: bash scripts/run_full_profiling.sh <config-name> [model] [users] [duration]
#   config-name: 描述性名字,如 burstgpt_70b_users6
#   model:        llama3.1-70b-instruct (default) | llama3.1-8b
#   users:        并发用户数 (default 6)
#   duration:     跑秒数 (default 300)
#
# 设计:
#   Trace 模式 (--io-trace-log) 用 NullBackend,不做真实硬件 I/O
#   bpftrace 需要真实 I/O 才能拿到直方图
#   → 必须分两轮跑
#
# Layer 1 (device):    iostat + pidstat + perf      (后台)
# Layer 2 (block):     bpftrace storage_latency_stack.sh (Round 2 only)
# Layer 3 (filesystem): --io-trace-log *.csv.zst     (Round 1 only)
# Layer 4 (KV object):  benchmark JSON/XLSX          (始终)

set -euo pipefail

CONFIG_NAME="${1:?Usage: run_full_profiling.sh <config-name> [model] [users] [duration]}"
MODEL="${2:-llama3.1-70b-instruct}"
USERS="${3:-6}"
DURATION="${4:-300}"

PROFILE_DIR="/home/ficus/llm/storage/results/kvcache-profile"
TS="$(date +%Y%m%d_%H%M%S)"
RUN_ID="${CONFIG_NAME}_${TS}"
LOG_DIR="${PROFILE_DIR}/profiling/${RUN_ID}"
CACHE_DIR="${PROFILE_DIR}/kv-cache-dir-${RUN_ID}"
mkdir -p "${LOG_DIR}"

echo "==================================================="
echo "Full 4-layer profiling: ${RUN_ID}"
echo "  model: ${MODEL}, users: ${USERS}, duration: ${DURATION}s"
echo "  log dir: ${LOG_DIR}"
echo "==================================================="

cd ~/llm/storage/kv_cache_benchmark
source ../.venv/bin/activate

# ── 启动 L1 device profiler (后台) ──
iostat -dx -m 1 > "${LOG_DIR}/iostat.log" 2>&1 &
IOSTAT_PID=$!
pidstat -d -r -s -u 1 > "${LOG_DIR}/pidstat.log" 2>&1 &
PIDSTAT_PID=$!

# perf stat 在 -a (system-wide) 模式需要 sudo。当前环境的 NOPASSWD 不一定可用,
# 所以这里做成可选: 能跑就跑, 不能跑就退化为空日志但不让脚本崩。
PERF_PID=""
if command -v perf >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo -n perf stat -e cache-misses,cache-references,cs,migrations,page-faults \
        sleep "${DURATION}" > "${LOG_DIR}/perf.log" 2>&1 &
    PERF_PID=$!
    echo "perf (sudo): enabled"
elif command -v perf >/dev/null 2>&1; then
    perf stat -e cache-misses,cache-references,cs,migrations,page-faults \
        sleep "${DURATION}" > "${LOG_DIR}/perf.log" 2>&1 &
    PERF_PID=$!
    echo "perf (no sudo, per-process only): enabled"
else
    echo "perf not installed: skipping"
fi

echo "Started L1 device profilers: iostat=$IOSTAT_PID pidstat=$PIDSTAT_PID perf=${PERF_PID:-skipped}"

# ── 检测 bpftrace 可用 ──
BPFTRACE_AVAILABLE=0
if command -v bpftrace >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    BPFTRACE_AVAILABLE=1
fi

cleanup() {
    echo "[cleanup] killing background profilers"
    kill $IOSTAT_PID $PIDSTAT_PID 2>/dev/null || true
    [ -n "$PERF_PID" ] && kill $PERF_PID 2>/dev/null || true
    # 不杀 bpftrace — 跑完 benchmark 后由 benchmark 自己发 SIGINT
    rm -rf "${CACHE_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

# ── ROUND 1: trace 模式 (io-trace-log + autoscaling) ──
echo ""
echo "▶ ROUND 1: trace 模式 (--io-trace-log + --enable-autoscaling)"
echo "  → 收集 KV cache 逻辑 I/O 模式 (Tier, Phase, Size)"
echo ""

TRACE_LOG="${LOG_DIR}/kv_trace.csv.zst"
BENCH_OUT="${PROFILE_DIR}/test_${RUN_ID}_trace.json"
BENCH_XLSX="${PROFILE_DIR}/test_${RUN_ID}_trace.xlsx"

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
    --io-trace-log "${TRACE_LOG}" \
    --enable-autoscaling \
    --log-level INFO \
    --output "${BENCH_OUT}" \
    --xlsx-output "${BENCH_XLSX}" \
    2>&1 | tee "${LOG_DIR}/round1_bench.log"

echo "✓ Round 1 完成: ${TRACE_LOG}, ${BENCH_OUT}"

# ── ROUND 2: 真实 I/O 模式 (bpftrace + 真实硬件) ──
echo ""
echo "▶ ROUND 2: 真实 I/O 模式 (--enable-latency-tracing + bpftrace)"
echo "  → 收集块层 Q2D/D2C 直方图, 自动蒸馏 fio job file"
echo ""

if [ $BPFTRACE_AVAILABLE -eq 1 ]; then
    # Round 2 单独的 cache dir 避免跟 Round 1 冲突
    CACHE_DIR2="${PROFILE_DIR}/kv-cache-dir-${RUN_ID}_hwio"
    mkdir -p "${CACHE_DIR2}"

    BENCH_OUT2="${PROFILE_DIR}/test_${RUN_ID}_hwio.json"
    BENCH_XLSX2="${PROFILE_DIR}/test_${RUN_ID}_hwio.xlsx"

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
        --enable-autoscaling \
        --log-level INFO \
        --output "${BENCH_OUT2}" \
        --xlsx-output "${BENCH_XLSX2}" \
        2>&1 | tee "${LOG_DIR}/round2_bench.log"

    echo "✓ Round 2 完成: ${BENCH_OUT2}"
    rm -rf "${CACHE_DIR2}" 2>/dev/null || true
else
    echo "⚠️  跳过 Round 2 (bpftrace 或 sudo 不可用)"
fi

echo ""
echo "==================================================="
echo "✓ Full profiling 完成: ${RUN_ID}"
echo "  产物目录: ${LOG_DIR}"
ls -la "${LOG_DIR}/" 2>&1 | head -20
echo "==================================================="