#!/usr/bin/env bash
# cross_vendor_t6_mixed_rw.sh
# Test 6: Mixed R/W (90/10 + 50/50) for all 4 NVMe SSDs.
# Models realistic LLM KV cache access pattern.
#
# Usage: bash scripts/cross_vendor_t6_mixed_rw.sh [DURATION]
#   DURATION per cell (default 90s)

set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE_DIR="$(pwd)"
export PROFILE_DIR
source scripts/cross_vendor_lib.sh

DURATION=${1:-${DURATION:-90}}
TEST_FILE_GB=20  # 20GB mixed randrw fits workload but exceeds SLC for steady-state read
BS=4k
IODEPTH=32
RWMIXES=(90 50)  # rwmixread percentages

VENDORS=(wd_sn570 biwin_x570 zhitai_ti600 seagate_fc530)
ROOT="$PROFILE_DIR/results/cross_vendor/t6_mixed_rw"
mkdir -p "$ROOT"

for vid in "${VENDORS[@]}"; do
  vendor_resolve "$vid"
  vendor_banner "$vid"

  RESULT_DIR="$ROOT/${vid}_$(date -u +%Y%m%d_%H%M%S)"
  mkdir -p "$RESULT_DIR"
  cd "$RESULT_DIR"

  TEST_FILE="$VENDOR_MOUNT/cross_vendor_t6_${vid}_${RANDOM}.dat"
  echo "  Test file: $TEST_FILE"

  for mix in "${RWMIXES[@]}"; do
    JOB="randrw_r${mix}w$((100-mix))"
    echo "  → ${JOB} bs=${BS} qd=${IODEPTH} (${DURATION}s)..."
    timeout $((DURATION + 10))s fio --name="$JOB" \
        --filename="$TEST_FILE" \
        --rw=randrw \
        --rwmixread=$mix \
        --bs=$BS \
        --size=${TEST_FILE_GB}G \
        --ioengine=libaio \
        --iodepth=$IODEPTH \
        --direct=1 \
        --runtime=$DURATION \
        --time_based \
        --output-format=json \
        --output="${JOB}.json" \
        --eta=never > /dev/null 2>&1 || echo "    ⚠ $JOB timed out / failed"
  done

  rm -f "$TEST_FILE"
  drop_caches
  echo "  ✓ $vid done -> $RESULT_DIR"
  cd "$PROFILE_DIR"
done

echo ""
echo "✅ Test 6 (mixed R/W) complete. Results under $ROOT/"