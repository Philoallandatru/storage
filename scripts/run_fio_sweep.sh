#!/usr/bin/env bash
# ============================================================================
# fio iodepth sweep — P0 #3 of KV-Cache AI SSD pre-study
# ============================================================================
# Take the 3 distilled fio .ini workloads from MLPerf Storage KV-Cache
# profiling, sweep iodepth across {32,64,128,256,1024} for each, plot latency
# vs queue depth to find the real saturation point of the SSD.
#
# Distilled workloads (from results/kvcache-profile/fio_*_profile_*.ini):
#   A) ShareGPT 8B TP8 CPU0.5g users=2          rwmixread=61% (real iodepth=1024)
#   B) BurstGPT 8B TP8 CPU0g users=2 sp1000    rwmixread=91% (real iodepth=524288)
#   C) Generic TP8 CPU0.5g                      rwmixread=73% (real iodepth=1048576)
#
# Why sweep iodepth?
#   The auto-distilled iodepth from bpftrace (524288 / 1048576) is the
#   *measured median queue depth during the real run* — which is unrealistic
#   for replay on a raw device, because the workload had 1024+ concurrent
#   workers all submitting in flight. Sweeping iodepth lets us find the
#   curve where latency goes from flat → knee → cliff, which is the actual
#   spec-relevant saturation point.
#
# Total runs:  3 workloads × 5 iodepth values = 15 runs
# Runtime per run: 60s (down from 300s in the originals; we only need
#   steady-state, not 5 minutes of it)
# Estimated wall: ~17 minutes
# ============================================================================
set -euo pipefail

RESULTS_BASE="/home/ficus/llm/storage/results/kvcache-profile/fio_sweep"
SRC_INI_BASE="/home/ficus/llm/storage/results/kvcache-profile"
TEST_FILE="${RESULTS_BASE}/fio_test.dat"
RUNTIME=60
PARSE_PY="/home/ficus/llm/storage/scripts/parse_fio_json.py"

IODEPTHS=(32 64 128 256 1024)

# The 3 workloads — name|ini_filename
WORKLOADS=(
    "sharegpt_8b_cpuhalf|${SRC_INI_BASE}/fio_sharegpt_8b_tp8_cpu0p5g_users2_300s_profile_20260608_014520.ini"
    "burstgpt_8b_cpurel_spd1000|${SRC_INI_BASE}/fio_burstgpt_8b_tp8_cpu0g_users2_300s_speedup1000_profile_20260608_070000.ini"
    "tp8_cpuhalf_generic|${SRC_INI_BASE}/fio_tp8_cpu0p5g_300s_profile_20260607_183517.ini"
)

mkdir -p "${RESULTS_BASE}"
cd "${RESULTS_BASE}"

# Prepare test file (20 GB) — large enough to defeat cache, small enough to be safe
echo "[prep] creating 20 GB test file..."
truncate -s 20G "${TEST_FILE}"

echo ""
echo "================================================================="
echo "fio iodepth sweep — $(date)"
echo "================================================================="

SUMMARY="${RESULTS_BASE}/sweep_summary.csv"
echo "workload,rwmixread_pct,iodepth,runtime_s,read_iops,read_bw_MiBs,write_iops,write_bw_MiBs,lat_read_p50_us,lat_read_p95_us,lat_read_p99_us,lat_read_p99_9_us,lat_write_p50_us,lat_write_p95_us,lat_write_p99_us,lat_write_p99_9_us" > "${SUMMARY}"

for wl_pair in "${WORKLOADS[@]}"; do
    WL_NAME="${wl_pair%%|*}"
    WL_INI="${wl_pair##*|}"
    WMIX=$(grep -oP 'rwmixread=\K\d+' "${WL_INI}" | head -1)

    echo ""
    echo "------ workload: ${WL_NAME}  rwmixread=${WMIX}% ------"
    echo "      source ini: ${WL_INI##*/}"

    for qd in "${IODEPTHS[@]}"; do
        RUN_DIR="${RESULTS_BASE}/${WL_NAME}_qd${qd}"
        mkdir -p "${RUN_DIR}"

        OUT_INI="${RUN_DIR}/fio_sweep.ini"
        {
            cat "${WL_INI}"
            echo ""
            echo "# ===== iodepth sweep override (qd=${qd}, runtime=${RUNTIME}s) ====="
            echo "filename=${TEST_FILE}"
            echo "runtime=${RUNTIME}"
            echo "iodepth=${qd}"
            echo "iodepth_batch_submit=${qd}"
        } > "${OUT_INI}"

        echo -n "[run] ${WL_NAME} qd=${qd} ... "
        if fio "${OUT_INI}" --output-format=json > "${RUN_DIR}/fio_output.json" 2> "${RUN_DIR}/fio_stderr.txt"; then
            METRICS=$(python3 "${PARSE_PY}" "${RUN_DIR}/fio_output.json" 2>&1) || METRICS="PARSE_FAIL"
            echo "${WL_NAME},${WMIX},${qd},${RUNTIME}${METRICS}" >> "${SUMMARY}"
            echo "OK"
        else
            echo "FAILED (see ${RUN_DIR}/fio_stderr.txt)"
        fi

        # brief settle between runs
        sleep 2
    done
done

echo ""
echo "================================================================="
echo "sweep complete: $(date)"
echo "results in: ${RESULTS_BASE}"
echo "================================================================="

# Clean up test file
echo "[cleanup] removing 20 GB test file..."
rm -f "${TEST_FILE}"
echo "done"