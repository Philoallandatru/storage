#!/usr/bin/env bash
# Measure SLC cache size in steady state (after GC has converged).
#
# Three-phase test:
#   Phase 1: Precondition the SSD with sequential write (~5 min)
#   Phase 2: Idle period to let GC converge (default 5 min, configurable)
#   Phase 3: Re-measure SLC cache using characterize_ssd_slc.py
#
# Compares fresh-state SLC cache (Phase 3 on fresh SSD) vs steady-state
# (Phase 3 after preconditioning + idle). This tells us how much SLC cache
# shrinks under realistic GC pressure.
#
# Disk space requirement: 2 × measurement_size_gb of free space
# (precondition + measurement files must coexist briefly).
# Defaults are 150 GiB precondition + 120 GiB measurement = 270 GiB needed.
#
# Usage:
#   ./measure_slc_cache_steady_state.sh [precondition_size_gb] [idle_seconds] [measurement_size_gb]

set -euo pipefail

PRECOND_GB="${1:-150}"
IDLE_SECONDS="${2:-300}"
MEASURE_GB="${3:-120}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_BASE="${REPO_ROOT}/results/ssd-characterization"
STAMP="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="${OUT_BASE}/ssd_slc_steady_state_${STAMP}"
mkdir -p "${RUN_DIR}"

# Free space check
FREE_GB=$(df -BG / | tail -1 | awk '{print $4}' | tr -d 'G')
NEEDED_GB=$((PRECOND_GB + MEASURE_GB + 10))
if [[ ${FREE_GB} -lt ${NEEDED_GB} ]]; then
    echo "ERROR: not enough free space. need=${NEEDED_GB}GiB free=${FREE_GB}GiB" >&2
    echo "Either reduce PRECOND_GB or MEASURE_GB, or free disk space." >&2
    exit 2
fi

echo "================================================================="
echo "Steady-State SLC Cache Test — $(date)"
echo "================================================================="
echo "  Precondition: ${PRECOND_GB} GiB sequential write"
echo "  Idle after preconditioning: ${IDLE_SECONDS} s"
echo "  Measurement size: ${MEASURE_GB} GiB"
echo "  Free space: ${FREE_GB} GiB (need ~${NEEDED_GB} GiB)"
echo "  Output: ${RUN_DIR}"
echo

# ---------------------------------------------------------------------------
# Phase 1: Precondition
# ---------------------------------------------------------------------------
echo "[phase 1/3] Preconditioning SSD with ${PRECOND_GB} GiB sequential write..."
PRECOND_FILE="${RUN_DIR}/precond.dat"

dd if=/dev/zero of="${PRECOND_FILE}" bs=1M count=$((PRECOND_GB * 1024)) \
    oflag=direct status=progress 2>&1 | tee "${RUN_DIR}/precond_dd.log"

sync
echo "  preconditioning done: $(date)"

# ---------------------------------------------------------------------------
# Phase 2: Idle for GC convergence
# ---------------------------------------------------------------------------
echo
echo "[phase 2/3] Idling for ${IDLE_SECONDS} s to let GC converge..."
sync
echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || \
    echo "  (warn: could not drop page caches — measurement may include cache effects)"

sleep "${IDLE_SECONDS}"
echo "  idle done: $(date)"

# ---------------------------------------------------------------------------
# Phase 3: Measure SLC cache (in steady state)
# ---------------------------------------------------------------------------
echo
echo "[phase 3/3] Measuring SLC cache in steady state (${MEASURE_GB} GiB)..."
cd "${REPO_ROOT}"

python3 scripts/characterize_ssd_slc.py \
    --target-dir "${OUT_BASE}" \
    --size-gb "${MEASURE_GB}" \
    --name "steady_state_${STAMP}" \
    --yes

# Cleanup preconditioning file (measurement file is cleaned by script)
rm -f "${PRECOND_FILE}"
echo "preconditioning file removed"

echo
echo "================================================================="
echo "Done. Compare this run's SLC cache against the fresh-state baseline:"
echo "  Fresh baseline:    results/ssd-characterization/ssd_slc_biwin_x570_200g_*/ssd_characterization_report.md"
echo "  Steady-state run:  ${OUT_BASE}/ssd_slc_steady_state_${STAMP}/ssd_characterization_report.md"
echo "================================================================="