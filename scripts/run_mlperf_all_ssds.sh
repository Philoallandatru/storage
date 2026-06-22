#!/usr/bin/env bash
# ============================================================================
# run_mlperf_all_ssds.sh — Run MLPerf Storage benchmark on all 4 SSDs in parallel
#
# Uses 4 background processes, one per vendor. Each runs ~10-15 minutes for
# checkpointing llama3-8b alone, and proportionally longer for the full
# training matrix on high-capacity disks.
#
# Usage:
#   bash scripts/run_mlperf_all_ssds.sh
#
# Output:
#   Each SSD: /mnt/ai_ssd{0,1,2}/.../mlperf_results/
#   Summary: results/cross_vendor/mlperf_summary.md (from aggregate script)
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Activate venv so subprocess calls can find mlpstorage, dlio_benchmark
# shellcheck source=/dev/null
source "$PROJECT_DIR/.venv/bin/activate"

VENDORS=(wd_sn570 biwin_x570 zhitai_ti600 seagate_fc530)
LOG_DIR="$PROJECT_DIR/results/cross_vendor/mlperf_run_logs"
mkdir -p "$LOG_DIR"

echo "================================================================"
echo " Launching parallel MLPerf Storage benchmark on 4 SSDs"
echo "================================================================"
echo ""
echo "Log directory: $LOG_DIR"
echo ""

declare -A PIDS

for vid in "${VENDORS[@]}"; do
    logfile="$LOG_DIR/${vid}.log"
    echo "[$vid] Starting in background, log: $logfile"
    bash "$SCRIPT_DIR/ssd_mlperf_benchmark.sh" "$vid" > "$logfile" 2>&1 &
    PIDS[$vid]=$!
done

echo ""
echo "All 4 SSDs running. PIDs:"
for vid in "${VENDORS[@]}"; do
    echo "  $vid → PID ${PIDS[$vid]}"
done
echo ""
echo "Monitor with: tail -f $LOG_DIR/<vendor>.log"
echo "Aggregate when done: python $SCRIPT_DIR/aggregate_mlperf_results.py"
echo ""

# Wait for all
FAILED=0
for vid in "${VENDORS[@]}"; do
    pid=${PIDS[$vid]}
    if wait "$pid"; then
        echo "[$vid] DONE (exit 0)"
    else
        rc=$?
        echo "[$vid] FAILED (exit $rc) — see $LOG_DIR/${vid}.log"
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo "================================================================"
echo " All 4 SSDs completed. $FAILED failed."
echo "================================================================"

echo ""
echo "Aggregate results:"
python3 "$SCRIPT_DIR/aggregate_mlperf_results.py"

exit $FAILED