#!/usr/bin/env bash
# cross_vendor_t7_pagecache.sh
# Test 7: Page cache sensitivity for all 4 NVMe SSDs.
#
# Two conditions per vendor:
#   1. buffered_warm    -- fio uses default buffered IO; OS caches the file.
#   2. buffered_evict   -- fio --invalidate=1, OS evicts each block after read.
#
# Metric: read BW, P99 latency, with and without cache.
# This isolates the DRAM page-cache effect without depending on cgroup v2
# (which does not track shared page cache anyway).
#
# Usage: bash scripts/cross_vendor_t7_pagecache.sh [DURATION]
#   DURATION per cell (default 60s)

set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE_DIR="$(pwd)"
export PROFILE_DIR
source scripts/cross_vendor_lib.sh

DURATION=${1:-${DURATION:-45}}
TEST_FILE_GB=6    # fits in DRAM (66 GB free) but > SLC for steady-state
BS=4k
IODEPTH=16

VENDORS=(wd_sn570 biwin_x570 zhitai_ti600 seagate_fc530)
ROOT="$PROFILE_DIR/results/cross_vendor/t7_pagecache"
mkdir -p "$ROOT"

for vid in "${VENDORS[@]}"; do
  vendor_resolve "$vid"
  vendor_banner "$vid"

  RESULT_DIR="$ROOT/${vid}_$(date -u +%Y%m%d_%H%M%S)"
  mkdir -p "$RESULT_DIR"
  cd "$RESULT_DIR"

  TEST_FILE="$VENDOR_MOUNT/cross_vendor_t7_${vid}_${RANDOM}.dat"
  echo "  Test file: $TEST_FILE (${TEST_FILE_GB} GB)"

  # === Condition 1: buffered warm (cache hits after first read) ===
  echo "  → buffered_warm (no invalidation)..."
  timeout $((DURATION * 2 + 15))s fio --name=buffered_warm \
      --filename="$TEST_FILE" \
      --rw=read \
      --bs=$BS \
      --size=${TEST_FILE_GB}G \
      --ioengine=libaio \
      --iodepth=$IODEPTH \
      --direct=0 \
      --runtime=$DURATION \
      --time_based \
      --output-format=json \
      --output=buffered_warm.json \
      --eta=never > /dev/null 2>&1 || echo "    ⚠ buffered_warm timed out"

  # === Condition 2: buffered with invalidate (cold page cache on each read) ===
  echo "  → buffered_evict (invalidate=1)..."
  drop_caches
  timeout $((DURATION * 2 + 15))s fio --name=buffered_evict \
      --filename="$TEST_FILE" \
      --rw=read \
      --bs=$BS \
      --size=${TEST_FILE_GB}G \
      --ioengine=libaio \
      --iodepth=$IODEPTH \
      --direct=0 \
      --invalidate=1 \
      --runtime=$DURATION \
      --time_based \
      --output-format=json \
      --output=buffered_evict.json \
      --eta=never > /dev/null 2>&1 || echo "    ⚠ buffered_evict timed out"

  rm -f "$TEST_FILE"
  drop_caches
  echo "  ✓ $vid done -> $RESULT_DIR"
  cd "$PROFILE_DIR"
done

echo ""
echo "✅ Test 7 (page cache) complete. Results under $ROOT/"