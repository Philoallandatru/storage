#!/usr/bin/env bash
# cross_vendor_t3_slc_steady.sh
# Test 3: Steady-state SLC cache size for all 4 NVMe SSDs.
# Same shape as the Biwin characterization (scripts/measure_slc_cache_steady_state.sh).
#
# Procedure per vendor:
#   1. Precondition: 200 GB sequential write + 5 min idle (drain SLC to baseline)
#   2. Measure: write 1MB slices, plot BW vs cumulative bytes, identify cliff
#
# Usage: bash scripts/cross_vendor_t3_slc_steady.sh

set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE_DIR="$(pwd)"
export PROFILE_DIR
source scripts/cross_vendor_lib.sh

PRECOND_GB=200
IDLE_MIN_AFTER_PRECOND=5
SLICE_GB=10

VENDORS=(wd_sn570 biwin_x570 zhitai_ti600 seagate_fc530)
ROOT="$PROFILE_DIR/results/cross_vendor/t3_slc_steady"
mkdir -p "$ROOT"

for vid in "${VENDORS[@]}"; do
  vendor_resolve "$vid"
  vendor_banner "$vid"

  RESULT_DIR="$ROOT/${vid}_$(date -u +%Y%m%d_%H%M%S)"
  mkdir -p "$RESULT_DIR"
  cd "$RESULT_DIR"

  FREE_KB=$(df --output=avail -k "$VENDOR_MOUNT" | tail -1 | tr -d ' ')
  FREE_GB=$((FREE_KB / 1024 / 1024))
  if (( FREE_GB < PRECOND_GB + 20 )); then
    echo "  ⚠ ${vid}: only ${FREE_GB} GB free; reducing PRECOND_GB to $((FREE_GB - 30))"
    PRECOND_GB=$((FREE_GB - 30))
  fi

  # === Step 1: precondition ===
  echo "  [1/3] Preconditioning: ${PRECOND_GB} GB sequential write..."
  PRECOND_FILE="$VENDOR_MOUNT/cross_vendor_t3_pre_${vid}_${RANDOM}.dat"
  fio --name=precond \
      --filename="$PRECOND_FILE" \
      --rw=write \
      --bs=1M \
      --size=${PRECOND_GB}G \
      --ioengine=libaio \
      --iodepth=32 \
      --direct=1 \
      --output-format=json \
      --output=precond.json \
      --eta=never > /dev/null 2>&1
  rm -f "$PRECOND_FILE"
  drop_caches

  # === Step 2: idle to let GC drain SLC to steady-state ===
  echo "  [2/3] Idle ${IDLE_MIN_AFTER_PRECOND} min for steady state..."
  sleep $((IDLE_MIN_AFTER_PRECOND * 60))

  # === Step 3: probe SLC size ===
  echo "  [3/3] Probing SLC cache with sequential 1MB writes..."
  PROBE_FILE="$VENDOR_MOUNT/cross_vendor_t3_probe_${vid}_${RANDOM}.dat"
  PROBE_TOTAL_GB=$((PRECOND_GB + 30))   # write more than SLC cache size
  NUM_SAMPLES=$((PROBE_TOTAL_GB / SLICE_GB))

  fio --name=probe \
      --filename="$PROBE_FILE" \
      --rw=write \
      --bs=1M \
      --size=${SLICE_GB}G \
      --ioengine=libaio \
      --iodepth=32 \
      --direct=1 \
      --numjobs=1 \
      --output-format=json \
      --output=probe.json \
      --eta=never \
      --write_bw_log=probe \
      --disable_slat=1 \
      --disable_clat=1 \
      --loops=$NUM_SAMPLES > /dev/null 2>&1
  rm -f "$PROBE_FILE"
  drop_caches

  echo "  ✓ $vid done -> $RESULT_DIR"
  cd "$PROFILE_DIR"
done

echo ""
echo "✅ Test 3 (SLC steady state) complete. Results under $ROOT/"