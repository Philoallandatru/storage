#!/usr/bin/env bash
# Continue P1 sweep: SSD already preconditioned with 570 GB
# Just run the 6 benchmark runs (3 workloads × 2 iodepths)
set -euo pipefail

RESULTS_BASE="/home/ficus/llm/storage/results/kvcache-profile/fio_sweep_precond"
SRC_INI_BASE_KVC="/home/ficus/llm/storage/results/kvcache-profile"
TEST_FILE="${RESULTS_BASE}/fio_test_20gb.dat"
TEST_SIZE="20G"
RUNTIME=60

IODEPTHS=(32 1024)

WORKLOADS=(
    "sharegpt_8b_cpuhalf|${SRC_INI_BASE_KVC}/fio_sharegpt_8b_tp8_cpu0p5g_users2_300s_profile_20260608_014520.ini"
    "burstgpt_8b_cpurel_spd1000|${SRC_INI_BASE_KVC}/fio_burstgpt_8b_tp8_cpu0g_users2_300s_speedup1000_profile_20260608_070000.ini"
    "tp8_cpuhalf_generic|${SRC_INI_BASE_KVC}/fio_tp8_cpu0p5g_300s_profile_20260607_183517.ini"
)

mkdir -p "${RESULTS_BASE}"
cd "${RESULTS_BASE}"

echo "================================================================="
echo "P1: fio sweep on already-preconditioned SSD — $(date)"
echo "================================================================="

echo "[phase 2] creating ${TEST_SIZE} test file..."
truncate -s ${TEST_SIZE} "${TEST_FILE}"

SUMMARY="${RESULTS_BASE}/sweep_precond_summary.csv"
echo "workload,rwmixread_pct,iodepth,runtime_s,read_iops,read_bw_MiBs,write_iops,write_bw_MiBs,lat_read_p50_us,lat_read_p95_us,lat_read_p99_us,lat_read_p99_9_us,lat_write_p50_us,lat_write_p95_us,lat_write_p99_us,lat_write_p99_9_us" > "${SUMMARY}"

PARSE_PY="/home/ficus/llm/storage/scripts/parse_fio_json.py"

for wl_pair in "${WORKLOADS[@]}"; do
    WL_NAME="${wl_pair%%|*}"
    WL_INI="${wl_pair##*|}"
    WMIX=$(grep -oP 'rwmixread=\K\d+' "${WL_INI}" | head -1)

    echo ""
    echo "------ workload: ${WL_NAME}  rwmixread=${WMIX}% ------"

    for qd in "${IODEPTHS[@]}"; do
        RUN_DIR="${RESULTS_BASE}/${WL_NAME}_qd${qd}"
        mkdir -p "${RUN_DIR}"

        OUT_INI="${RUN_DIR}/fio_sweep.ini"
        {
            cat "${WL_INI}"
            echo ""
            echo "# ===== iodepth sweep override (qd=${qd}, runtime=${RUNTIME}s) — preconditioned SSD ====="
            echo "filename=${TEST_FILE}"
            echo "runtime=${RUNTIME}"
            echo "iodepth=${qd}"
            echo "iodepth_batch_submit=${qd}"
        } > "${OUT_INI}"

        sync
        if [ -w /proc/sys/vm/drop_caches ]; then
            echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
        fi

        echo -n "[run] ${WL_NAME} qd=${qd} ... "
        if fio "${OUT_INI}" --output-format=json > "${RUN_DIR}/fio_output.json" 2> "${RUN_DIR}/fio_stderr.txt"; then
            METRICS=$(python3 "${PARSE_PY}" "${RUN_DIR}/fio_output.json" 2>&1) || METRICS="PARSE_FAIL"
            echo "${WL_NAME},${WMIX},${qd},${RUNTIME}${METRICS}" >> "${SUMMARY}"
            echo "OK"
        else
            echo "FAILED (see ${RUN_DIR}/fio_stderr.txt)"
        fi

        sleep 2
    done
done

echo ""
echo "================================================================="
echo "[cleanup] — $(date)"
echo "================================================================="
echo "[cleanup] removing test file (precondition file already cleaned)..."
rm -f "${TEST_FILE}"
echo "done"
echo ""
echo "precondition sweep results: ${RESULTS_BASE}/sweep_precond_summary.csv"