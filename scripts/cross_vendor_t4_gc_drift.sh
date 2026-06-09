#!/usr/bin/env bash
# cross_vendor_t4_gc_drift.sh
# Test 4: GC drift over 15 minutes per vendor (serial, 4 disks = 60 min total).
#
# Same shape as scripts/run_long_steady_state.sh but parameterized for each
# vendor mount.
#
# Usage: bash scripts/cross_vendor_t4_gc_drift.sh [DURATION_MIN]
#   DURATION_MIN default 15

set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE_DIR="$(pwd)"
export PROFILE_DIR
source scripts/cross_vendor_lib.sh

DURATION_MIN=${1:-${DURATION_MIN:-15}}
DURATION=$((DURATION_MIN * 60))

VENDORS=(wd_sn570 biwin_x570 zhitai_ti600 seagate_fc530)
ROOT="$PROFILE_DIR/results/cross_vendor/t4_gc_drift"
mkdir -p "$ROOT"

for vid in "${VENDORS[@]}"; do
  vendor_resolve "$vid"
  vendor_banner "$vid"

  RESULT_DIR="$ROOT/${vid}_$(date -u +%Y%m%d_%H%M%S)"
  mkdir -p "$RESULT_DIR"
  cd "$RESULT_DIR"

  # Use a simple fio job that drives sustained mixed IO, mimicking LLM
  # inference prefill+decode (read-heavy). The same approach as the Biwin
  # characterization: 16k random read, QD=4, direct=1, time_based.
  TEST_FILE="$VENDOR_MOUNT/cross_vendor_t4_${vid}_${RANDOM}.dat"
  echo "  Test file: $TEST_FILE, duration: ${DURATION}s (${DURATION_MIN}min)"
  drop_caches

  # Background sampler: iostat -dx -m 1
  iostat -dx -m 1 > iostat.txt 2>&1 &
  SAMPLER_PID=$!
  sleep 1  # let sampler warm up

  timeout $((DURATION + 30))s fio --name=long_steady \
      --filename="$TEST_FILE" \
      --rw=randread \
      --bs=16k \
      --size=20G \
      --ioengine=libaio \
      --iodepth=4 \
      --direct=1 \
      --runtime=$DURATION \
      --time_based \
      --output-format=json \
      --output=long_steady.json \
      --eta=never > /dev/null 2>&1 || echo "    ⚠ long_steady timed out"

  # Stop iostat sampler (SIGTERM, ignore exit code)
  kill $SAMPLER_PID 2>/dev/null || true
  wait $SAMPLER_PID 2>/dev/null || true

  rm -f "$TEST_FILE"
  drop_caches
  echo "  ✓ $vid done -> $RESULT_DIR"
  cd "$PROFILE_DIR"
done

echo ""
echo "✅ Test 4 (GC drift) complete. Results under $ROOT/"