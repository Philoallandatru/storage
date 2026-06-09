#!/usr/bin/env bash
# Page cache sensitivity sweep — does DRAM help or hurt SSD-bound KV cache?
#
# Test matrix (4 cells):
#   - dram_unlimited:  no cap, default Linux page cache behavior
#   - dram_32gb:       cgroup memory.max=32GB
#   - dram_8gb:        cgroup memory.max=8GB
#   - dram_8gb_evict:  same as dram_8gb BUT with fio --invalidate=1
#                      (drop page cache after every I/O, simulating
#                       "DRAM constantly evicting", worst-case for SSD)
#
# Why 4 cells:
#   In cgroup v2, memory.max does NOT limit the shared kernel page cache.
#   So cgroup alone does not force DRAM pressure. fio --invalidate=1 is a
#   reliable way to force cache misses regardless of cgroup behavior.
#
# Method:
#   Replay the distilled BurstGPT 70B users=6 fio workload under each DRAM
#   limit, with direct=0 (buffered IO, so page cache IS used). The test
#   file is sized larger than the DRAM limit so page cache must evict
#   during the run.
#
# Important:
#   - direct=0 is required: with direct=1 fio bypasses page cache and the
#     DRAM limit has no effect.
#   - cgroup v2 memory controller only accounts for cgroup-local pages,
#     so the timeline samples capture only the buffered IO cache footprint.
#   - Page cache is dropped via /proc/sys/vm/drop_caches between cells.

set -euo pipefail

DURATION="${DURATION:-120}"
TEST_FILE_SIZE_GB="${TEST_FILE_SIZE_GB:-40}"
RESULTS_BASE="/home/ficus/llm/storage/results/kvcache-profile"
PROFILE_DIR="${RESULTS_BASE}/pagecache_sweep"
mkdir -p "${PROFILE_DIR}"

SOURCE_JSON=$(ls -t "${RESULTS_BASE}"/test_burstgpt_70b_users6_full_*_hwio.json 2>/dev/null | head -1)
if [ -z "${SOURCE_JSON}" ] || [ ! -f "${SOURCE_JSON}" ]; then
    echo "ERROR: no distilled BurstGPT 70B users=6 JSON found under ${RESULTS_BASE}"
    exit 1
fi

TS="$(date +%Y%m%d_%H%M%S)"

echo "==================================================="
echo "Page cache sensitivity sweep"
echo "  source JSON:  ${SOURCE_JSON##*/}"
echo "  duration:     ${DURATION}s per cell"
echo "  test file:    ${TEST_FILE_SIZE_GB} GiB (buffered IO, direct=0)"
echo "==================================================="

# ── write the worker script (runs as root) ──
WORKER="${PROFILE_DIR}/.worker_${TS}.sh"
cat > "${WORKER}" <<'WORKER_EOF'
#!/usr/bin/env bash
set -euo pipefail

LABEL="$1"
MEM_MAX="$2"
TEST_FILE="$3"
SOURCE_JSON="$4"
DURATION="$5"
TEST_FILE_SIZE_GB="$6"
RUN_DIR="$7"

CGROUP_PATH="/sys/fs/cgroup/kvcache_pagecache_test_${LABEL}"

echo ""
echo "▶ Cell: ${LABEL} (memory.max=${MEM_MAX})"

# setup cgroup
rm -rf "${CGROUP_PATH}" 2>/dev/null || true
mkdir -p "${CGROUP_PATH}"
echo "+memory" > /sys/fs/cgroup/cgroup.subtree_control 2>/dev/null || true

if [ "${MEM_MAX}" = "max" ]; then
    echo "max" > "${CGROUP_PATH}/memory.max"
else
    echo "${MEM_MAX}" > "${CGROUP_PATH}/memory.max"
fi
echo "max" > "${CGROUP_PATH}/memory.swap.max"

# drop page cache before starting
sync
echo 3 > /proc/sys/vm/drop_caches

# generate fio config from distilled workload, with direct=0 (buffered)
FIO_INI="${RUN_DIR}/workload.ini"
python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
fio = data['fio_workload']
fio = fio.replace('ioengine=libaio', 'ioengine=psync')
# BUFFERED IO — we want DRAM page cache to actually matter
fio = fio.replace('direct=1', 'direct=0')
fio = fio.replace('runtime=300', 'runtime=' + sys.argv[2])
fio = fio.replace('iodepth=32768', 'iodepth=32')
fio = fio.replace('iodepth_batch_submit=32768', '')
fio = fio.replace('iodepth_batch_complete_min=1', '')
fio = fio.replace('--filename=/dev/nvmeXn1', '')
print(fio)
" "${SOURCE_JSON}" "${DURATION}" > "${FIO_INI}"
cat >> "${FIO_INI}" <<EOF
filename=${TEST_FILE}
size=${TEST_FILE_SIZE_GB}G
EOF

# drop caches again
sync
echo 3 > /proc/sys/vm/drop_caches

# start iostat
iostat -dx -m 1 > "${RUN_DIR}/iostat.log" 2>&1 &
IOSTAT_PID=$!

# run fio in subshell, attach subshell to cgroup first
run_label="fio"
if [ "${LABEL}" = "dram_8gb_evict" ]; then
    # Patch the generated ini to add --invalidate=1 (drop pages after every I/O)
    sed -i 's|^refill_buffers=1|refill_buffers=1\ninvalidate=1|' "${FIO_INI}"
    run_label="fio (invalidate=1)"
fi
(
    set +e
    echo $$ > "${CGROUP_PATH}/cgroup.procs"
    cd "${RUN_DIR}"
    # Memory sampler — poll memory.current every second
    while true; do
        cat "${CGROUP_PATH}/memory.current" 2>/dev/null >> "${RUN_DIR}/memory_current_timeline.log"
        sleep 1
    done &
    SAMPLER_PID=$!
    fio "${FIO_INI}" > "${RUN_DIR}/fio.log" 2>&1
    echo "FIO_EXIT=$?" > "${RUN_DIR}/fio_exit.log"
    kill $SAMPLER_PID 2>/dev/null
    wait $SAMPLER_PID 2>/dev/null
    true
) &
FIO_PID=$!

wait "${FIO_PID}"

kill "${IOSTAT_PID}" 2>/dev/null || true
wait "${IOSTAT_PID}" 2>/dev/null || true

# cgroup stats snapshot
{
    echo "=== cgroup ${LABEL} memory stats (post-fio) ==="
    cat "${CGROUP_PATH}/memory.peak" 2>/dev/null | awk '{printf "memory.peak    = %d bytes (%.2f GiB)\n", $1, $1/1024/1024/1024}'
    cat "${CGROUP_PATH}/memory.current" 2>/dev/null | awk '{printf "memory.current = %d bytes (%.2f GiB)\n", $1, $1/1024/1024/1024}'
    echo "=== memory.events ==="
    cat "${CGROUP_PATH}/memory.events" 2>/dev/null
    echo "=== memory.stat (top 10) ==="
    cat "${CGROUP_PATH}/memory.stat" 2>/dev/null | head -10
} > "${RUN_DIR}/cgroup_memory.log"

# Post-process memory timeline
if [ -s "${RUN_DIR}/memory_current_timeline.log" ]; then
    python3 -c "
import statistics, sys
path = sys.argv[1]
vals = [int(x) for x in open(path).read().split() if x.strip().isdigit()]
if vals:
    print(f'samples    : {len(vals)}')
    print(f'min        : {min(vals)/1024/1024:.2f} MiB')
    print(f'mean       : {statistics.mean(vals)/1024/1024:.2f} MiB')
    print(f'max        : {max(vals)/1024/1024:.2f} MiB')
    print(f'p99        : {sorted(vals)[int(len(vals)*0.99)]/1024/1024:.2f} MiB')
" "${RUN_DIR}/memory_current_timeline.log" > "${RUN_DIR}/cgroup_memory_timeline_stats.log"
fi

# system-wide snapshot
{
    grep -E "MemTotal|MemFree|MemAvailable|Buffers|Cached|Dirty|Writeback" /proc/meminfo
} > "${RUN_DIR}/meminfo_end.log"

# cleanup
rmdir "${CGROUP_PATH}" 2>/dev/null || true
rm -f "${TEST_FILE}"

echo "  ✓ cell complete: ${LABEL}"
WORKER_EOF
chmod +x "${WORKER}"

# ── orchestration (unprivileged) ──
GIB=$((1024*1024*1024))

run_cell() {
    local label="$1"
    local mem_max="$2"
    local run_dir="${PROFILE_DIR}/${label}_${TS}"
    mkdir -p "${run_dir}"
    local test_file="${run_dir}/test_file.bin"

    sudo "${WORKER}" "${label}" "${mem_max}" "${test_file}" "${SOURCE_JSON}" "${DURATION}" "${TEST_FILE_SIZE_GB}" "${run_dir}"

    echo ""
    echo "  📊 ${label} fio result:"
    if [ -f "${run_dir}/fio_exit.log" ]; then
        cat "${run_dir}/fio_exit.log"
    fi
    if [ -f "${run_dir}/fio.log" ]; then
        grep -E "^ *(READ|WRITE):" "${run_dir}/fio.log" | head -5
        grep "clat percentiles" "${run_dir}/fio.log" | head -4
    fi
}

echo ""
echo "=== Cell 1/4: dram_unlimited ==="
run_cell "dram_unlimited" "max"

echo ""
echo "=== Cell 2/4: dram_32gb ==="
run_cell "dram_32gb" "$((32 * GIB))"

echo ""
echo "=== Cell 3/4: dram_8gb ==="
run_cell "dram_8gb" "$((8 * GIB))"

echo ""
echo "=== Cell 4/4: dram_8gb_evict (fio --invalidate=1) ==="
run_cell "dram_8gb_evict" "$((8 * GIB))"

# cleanup worker
rm -f "${WORKER}"

echo ""
echo "==================================================="
echo "✓ Page cache sensitivity sweep complete"
echo "  results: ${PROFILE_DIR}/*_${TS}/"
echo "==================================================="