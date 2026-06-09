#!/usr/bin/env bash
# cross_vendor_t5_random4k.sh
# Test 5: Random 4K IOPS at multiple queue depths for all 4 NVMe SSDs.
#
# Sweep iodepth 1, 4, 16, 64, 256 for both randread and randwrite.
# Report IOPS, BW, latency (mean, P99).
#
# Usage: bash scripts/cross_vendor_t5_random4k.sh [DURATION]
#   DURATION per QD-cell (default 30s)

set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE_DIR="$(pwd)"
export PROFILE_DIR
source scripts/cross_vendor_lib.sh

DURATION=${1:-${DURATION:-30}}
TEST_FILE_GB=4  # 4GB fits in any SLC cache and keeps test self-contained
BS=4k
IODEPTHS=(1 4 16 64 256)

VENDORS=(wd_sn570 biwin_x570 zhitai_ti600 seagate_fc530)
ROOT="$PROFILE_DIR/results/cross_vendor/t5_random4k"
mkdir -p "$ROOT"

for vid in "${VENDORS[@]}"; do
  vendor_resolve "$vid"
  vendor_banner "$vid"

  RESULT_DIR="$ROOT/${vid}_$(date -u +%Y%m%d_%H%M%S)"
  mkdir -p "$RESULT_DIR"
  cd "$RESULT_DIR"

  TEST_FILE="$VENDOR_MOUNT/cross_vendor_t5_${vid}_${RANDOM}.dat"
  echo "  Test file: $TEST_FILE"

  for rw in randread randwrite; do
    for qd in "${IODEPTHS[@]}"; do
      echo "  → ${rw} bs=${BS} qd=${qd} (${DURATION}s)..."
      JOB="${rw}_qd${qd}"
      timeout $((DURATION + 10))s fio --name="$JOB" \
          --filename="$TEST_FILE" \
          --rw=$rw \
          --bs=$BS \
          --size=${TEST_FILE_GB}G \
          --ioengine=libaio \
          --iodepth=$qd \
          --direct=1 \
          --runtime=$DURATION \
          --time_based \
          --output-format=json \
          --output="${JOB}.json" \
          --eta=never > /dev/null 2>&1 || echo "    ⚠ $JOB timed out / failed"
    done
  done

  rm -f "$TEST_FILE"
  drop_caches
  echo "  ✓ $vid done -> $RESULT_DIR"
  cd "$PROFILE_DIR"
done

echo ""
echo "✅ Test 5 (4K random IOPS) complete. Results under $ROOT/"