#!/usr/bin/env bash
# ============================================================================
# P1: SSD preconditioning fio sweep
# ============================================================================
# Pre-fill the SSD with sequential writes (100GB) to push past any SLC cache
# into the device's native TLC/QLC steady state. Then re-run a reduced version
# of the iodepth sweep to compare pre vs post preconditioning.
#
# Why?
#   Modern NVMe SSDs use a small fast SLC cache (~10-30GB typically). On a
#   fresh device, the first ~30GB of writes go into SLC, looking much faster
#   than TLC. Pre-filling forces writes into the steady-state region.
#
# What we compare:
#   For each of 3 workloads × {qd=32, qd=1024}, compare:
#     - Pre  (original sweep, on fresh SSD):   results/kvcache-profile/fio_sweep/
#     - Post (this script, after 100GB write): results/kvcache-profile/fio_sweep_precond/
#
# Note: we use direct=1 so page cache is irrelevant. We just need to
# actually write 100GB to the device before measuring.
#
# Estimated time: 100GB sequential write (~3-5 min) + 6 fio runs (60s each)
#                 + analysis = ~15 min total
# ============================================================================
set -euo pipefail

RESULTS_BASE="/home/ficus/llm/storage/results/kvcache-profile/fio_sweep_precond"
SRC_INI_BASE_KVC="/home/ficus/llm/storage/results/kvcache-profile"

PRECOND_FILE="${RESULTS_BASE}/precondition_100gb.dat"
TEST_FILE="${RESULTS_BASE}/fio_test_20gb.dat"
PRECOND_SIZE="100G"
TEST_SIZE="20G"
RUNTIME=60

# Reduced iodepth sweep: qd=32 (best case from previous sweep) + qd=1024 (worst case)
IODEPTHS=(32 1024)

WORKLOADS=(
    "sharegpt_8b_cpuhalf|${SRC_INI_BASE_KVC}/fio_sharegpt_8b_tp8_cpu0p5g_users2_300s_profile_20260608_014520.ini"
    "burstgpt_8b_cpurel_spd1000|${SRC_INI_BASE_KVC}/fio_burstgpt_8b_tp8_cpu0g_users2_300s_speedup1000_profile_20260608_070000.ini"
    "tp8_cpuhalf_generic|${SRC_INI_BASE_KVC}/fio_tp8_cpu0p5g_300s_profile_20260607_183517.ini"
)

mkdir -p "${RESULTS_BASE}"
cd "${RESULTS_BASE}"

echo "================================================================="
echo "P1: SSD preconditioning fio sweep — $(date)"
echo "================================================================="

# ---------------------------------------------------------------------------
# Phase 1: Pre-fill the SSD with sequential writes (100GB)
# ---------------------------------------------------------------------------
echo ""
echo "[phase 1] creating ${PRECOND_SIZE} precondition file (sequential write)..."
truncate -s ${PRECOND_SIZE} "${PRECOND_FILE}"

echo "[phase 1] filling SSD with 100GB sequential writes..."
fio --name=precondition \
    --filename="${PRECOND_FILE}" \
    --rw=write \
    --bs=128k \
    --size=${PRECOND_SIZE} \
    --runtime=600 \
    --time_based \
    --ioengine=libaio \
    --iodepth=32 \
    --direct=1 \
    --numjobs=1 \
    --group_reporting \
    --output-format=json,normal \
    > precondition.json 2>&1
echo "[phase 1] preconditioning complete: $(date)"
python3 -c "
import json
d = json.load(open('precondition.json'))
j = d['jobs'][0]
w = j['write']
print(f'  bytes_written={w[\"io_bytes\"]/1024**3:.1f} GiB')
print(f'  bw={w[\"bw\"]/1024:.1f} MiB/s')
print(f'  iops={w[\"iops\"]:.0f}')
print(f'  runtime={w[\"runtime\"]/1e9:.1f} s')
"

# ---------------------------------------------------------------------------
# Phase 2: Run reduced fio sweep (3 workloads × 2 iodepths = 6 runs)
# ---------------------------------------------------------------------------
echo ""
echo "================================================================="
echo "[phase 2] running fio sweep on preconditioned SSD — $(date)"
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

        # Best-effort cache drop (works without sudo if not configured)
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
echo "[phase 3] cleanup — $(date)"
echo "================================================================="
echo "[cleanup] removing precondition file + test file..."
rm -f "${PRECOND_FILE}" "${TEST_FILE}"
echo "done"
echo ""
echo "precondition sweep results: ${RESULTS_BASE}/sweep_precond_summary.csv"