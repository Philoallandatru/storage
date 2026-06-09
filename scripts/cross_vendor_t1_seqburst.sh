#!/usr/bin/env bash
# cross_vendor_t1_seqburst.sh
# Test 1: Sequential burst R/W for all 4 NVMe SSDs.
# Purpose: verify vendor datasheet claims for peak seq R/W.
#
# Usage: bash scripts/cross_vendor_t1_seqburst.sh [DURATION]
#   DURATION (default 60s)

set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE_DIR="$(pwd)"
export PROFILE_DIR
source scripts/cross_vendor_lib.sh

DURATION=${1:-${DURATION:-60}}
TEST_FILE_SIZE_GB=10   # 10 GB file keeps us well under SLC cache
BS=128k
IODEPTH=32

VENDORS=(${SMOKE_VENDOR:-wd_sn570 biwin_x570 zhitai_ti600 seagate_fc530})
ROOT="$PROFILE_DIR/results/cross_vendor/t1_seqburst"
mkdir -p "$ROOT"

for vid in "${VENDORS[@]}"; do
  vendor_resolve "$vid"
  vendor_banner "$vid"

  RESULT_DIR="$ROOT/${vid}_$(date -u +%Y%m%d_%H%M%S)"
  mkdir -p "$RESULT_DIR"
  cd "$RESULT_DIR"

  # Use a unique filename per vendor to avoid cross-mount confusion
  TEST_FILE="$VENDOR_MOUNT/cross_vendor_t1_${vid}_${RANDOM}.dat"
  echo "Test file: $TEST_FILE ($(hr_bytes $((TEST_FILE_SIZE_GB * 2**30))))"

  # Sequential read burst
  echo "  → Sequential READ burst..."
  drop_caches
  timeout $((DURATION + 10))s fio --name=seq_read_burst \
      --filename="$TEST_FILE" \
      --rw=read \
      --bs=$BS \
      --size=${TEST_FILE_SIZE_GB}G \
      --ioengine=libaio \
      --iodepth=$IODEPTH \
      --direct=1 \
      --runtime=$DURATION \
      --time_based \
      --output-format=json \
      --output=seq_read.json \
      --eta=never
  drop_caches

  # Sequential write burst (file must exist; we just overwrote it with reads,
  # but direct=1 read doesn't zero blocks. Use a fresh write target.)
  TEST_FILE_W="$VENDOR_MOUNT/cross_vendor_t1_w_${vid}_${RANDOM}.dat"
  rm -f "$TEST_FILE" "$TEST_FILE_W"
  echo "  → Sequential WRITE burst..."
  timeout $((DURATION + 10))s fio --name=seq_write_burst \
      --filename="$TEST_FILE_W" \
      --rw=write \
      --bs=$BS \
      --size=${TEST_FILE_SIZE_GB}G \
      --ioengine=libaio \
      --iodepth=$IODEPTH \
      --direct=1 \
      --runtime=$DURATION \
      --time_based \
      --output-format=json \
      --output=seq_write.json \
      --eta=never

  # Cleanup
  rm -f "$TEST_FILE" "$TEST_FILE_W"
  echo "  ✓ $vid done -> $RESULT_DIR"
  cd "$PROFILE_DIR"
done

echo ""
echo "✅ Test 1 (sequential burst) complete. Results under $ROOT/"