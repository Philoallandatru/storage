#!/usr/bin/env bash
# cross_vendor_t2_slc_fresh.sh
# Test 2: SLC cache size on a fresh-ish drive for all 4 NVMe SSDs.
#
# IMPORTANT: Each drive is not literally fresh (we cannot TRIM the OS partition).
# We approximate "fresh" by writing a large volume that fully consumes SLC, then
# idle 5 min for SLC to refill. The "fresh" SLC size here is the maximum observed
# before the first cliff.
#
# We don't TRIM (would require unmounting the root partition), but instead let
# the controller's idle GC flush its buffer. After 5 min idle, any consumed SLC
# should be back.
#
# Usage: bash scripts/cross_vendor_t2_slc_fresh.sh [WRITE_GB] [IDLE_MIN]
#   WRITE_GB  default 200 (total write volume, sequential)
#   IDLE_MIN  default 5   (idle before measurement, to let SLC refill)
#
# NOTE: This test does NOT precondition the disk — that is Test 3's job. We
# use a 200GB sequential write to characterize the SLC curve on a representative
# populated state. The "fresh" curve still appears because the 5 min idle lets
# the controller process its GC queue.

set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE_DIR="$(pwd)"
export PROFILE_DIR
source scripts/cross_vendor_lib.sh

WRITE_GB=${1:-${WRITE_GB:-200}}
IDLE_MIN=${2:-${IDLE_MIN:-5}}
SLICE_GB=10  # size of each sequential write slice (small = fine resolution)

VENDORS=(wd_sn570 biwin_x570 zhitai_ti600 seagate_fc530)
ROOT="$PROFILE_DIR/results/cross_vendor/t2_slc_fresh"
mkdir -p "$ROOT"

for vid in "${VENDORS[@]}"; do
  vendor_resolve "$vid"
  vendor_banner "$vid"

  RESULT_DIR="$ROOT/${vid}_$(date -u +%Y%m%d_%H%M%S)"
  mkdir -p "$RESULT_DIR"
  cd "$RESULT_DIR"

  # Sanity check: do we have enough free space? Each slice needs SLICE_GB free,
  # but the file grows cumulatively. WRITE_GB total.
  FREE_KB=$(df --output=avail -k "$VENDOR_MOUNT" | tail -1 | tr -d ' ')
  FREE_GB=$((FREE_KB / 1024 / 1024))
  if (( FREE_GB < WRITE_GB + 20 )); then
    echo "  ⚠ ${vid}: only ${FREE_GB} GB free, need $((WRITE_GB + 20)) GB; reducing WRITE_GB to $((FREE_GB - 30))"
    WRITE_GB=$((FREE_GB - 30))
  fi

  TEST_FILE="$VENDOR_MOUNT/cross_vendor_t2_${vid}_${RANDOM}.dat"
  echo "  Test file: $TEST_FILE, total write: ${WRITE_GB} GB"

  # Use fio's sequential write + periodic bw_log to find the SLC cliff
  NUM_SAMPLES=$((WRITE_GB / SLICE_GB))
  echo "  Capturing ${NUM_SAMPLES} slices of ${SLICE_GB} GB each..."

  fio --name=slc_probe \
      --filename="$TEST_FILE" \
      --rw=write \
      --bs=1M \
      --size=${SLICE_GB}G \
      --ioengine=libaio \
      --iodepth=32 \
      --direct=1 \
      --numjobs=1 \
      --output-format=json \
      --output=slc_probe.json \
      --eta=never \
      --write_bw_log=slc_probe \
      --disable_slat=1 \
      --disable_clat=1 \
      --loops=$NUM_SAMPLES > /tmp/t2_${vid}.log 2>&1

  echo "  → Idle ${IDLE_MIN} min for SLC refill..."
  sleep $((IDLE_MIN * 60))

  # Post-idle SLC sanity: write another slice, see if BW is back to "fresh" level
  TEST_FILE2="$VENDOR_MOUNT/cross_vendor_t2_idle_${vid}_${RANDOM}.dat"
  fio --name=slc_postidle \
      --filename="$TEST_FILE2" \
      --rw=write \
      --bs=1M \
      --size=${SLICE_GB}G \
      --ioengine=libaio \
      --iodepth=32 \
      --direct=1 \
      --output-format=json \
      --output=slc_postidle.json \
      --eta=never > /dev/null 2>&1

  rm -f "$TEST_FILE" "$TEST_FILE2"
  drop_caches  # don't pollute next vendor's test
  echo "  ✓ $vid done -> $RESULT_DIR"
  cd "$PROFILE_DIR"
done

echo ""
echo "✅ Test 2 (SLC fresh) complete. Results under $ROOT/"