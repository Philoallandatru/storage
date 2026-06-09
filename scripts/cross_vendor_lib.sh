#!/usr/bin/env bash
# cross_vendor_lib.sh
# Library of common functions for 4-vendor NVMe SSD comparison.
# Sourced by individual test scripts; not executed directly.
#
# Discovered: 4 consumer NVMe SSDs available locally:
#   nvme0: WD SN570         894 GB   (DRAM-less entry-level)
#   nvme1: Biwin X570       954 GB   (main subject of prior characterization)
#   nvme2: ZhiTai Ti600     932 GB   (YMTC NAND, domestic)
#   nvme3: Seagate FC530    932 GB   (Phison E18, high-end)
#
# Mounts:
#   /mnt/ai_ssd0           -> nvme0n1p2
#   /mnt/ai_ssd1           -> nvme2n1p3   (note: swapped slot order in mounts)
#   /mnt/ai_ssd2           -> nvme3n1p2
#   /run/media/ficus/...   -> nvme1n1p2   (root disk)
#
# This file is sourced, so we define functions and readonly vars.

# Cross-vendor device table.
# Format: short_id|kernel_dev|model|mount_point|free_gb
declare -rA VENDOR_DEV=(
  [wd_sn570]="nvme0|WDC WDS960G2G0C-00AJM0|/mnt/ai_ssd0|201"
  [biwin_x570]="nvme1|BIWIN X570 1TB|/run/media/ficus/新加卷|564"
  [zhitai_ti600]="nvme2|ZHITAI Ti600 1TB|/mnt/ai_ssd1|196"
  [seagate_fc530]="nvme3|Seagate ZP1000GV30012|/mnt/ai_ssd2|378"
)

# Market positioning (for the final report)
declare -rA VENDOR_TIER=(
  [wd_sn570]="entry-level (DRAM-less)"
  [biwin_x570]="mainstream (DRAM, prior subject)"
  [zhitai_ti600]="domestic (YMTC NAND)"
  [seagate_fc530]="high-end (Phison E18)"
)

# Color codes for readable per-disk output
readonly C_WD="\033[1;34m"        # blue
readonly C_BIWIN="\033[1;32m"     # green
readonly C_TI600="\033[1;31m"     # red
readonly C_SEAGATE="\033[1;33m"   # yellow
readonly C_RST="\033[0m"

# Pretty-print a banner indicating which vendor's results follow.
# Usage: vendor_banner <vendor_id>
vendor_banner() {
  local vid=$1
  local color
  case "$vid" in
    wd_sn570)        color=$C_WD      ;;
    biwin_x570)      color=$C_BIWIN   ;;
    zhitai_ti600)    color=$C_TI600   ;;
    seagate_fc530)   color=$C_SEAGATE ;;
    *)               color=$C_RST     ;;
  esac
  local model="${VENDOR_DEV[$vid]}"
  local mount="${VENDOR_DEV[$vid]##*|}"   # wrong — kept for parity below
  # Correct field extraction: split by '|'
  IFS='|' read -r _dev model mount _free <<< "${VENDOR_DEV[$vid]}"
  echo -e "${color}========================================================"
  echo -e "  VENDOR: $vid"
  echo -e "  MODEL:  $model"
  echo -e "  MOUNT:  $mount"
  echo -e "  TIER:   ${VENDOR_TIER[$vid]}"
  echo -e "========================================================${C_RST}"
}

# Resolve a vendor id to its mount point and free-space.
# Sets globals: VENDOR_MOUNT, VENDOR_FREE_GB, VENDOR_DEV_NAME
# Usage: vendor_resolve <vendor_id>
vendor_resolve() {
  local vid=$1
  IFS='|' read -r VENDOR_DEV_NAME _model VENDOR_MOUNT VENDOR_FREE_GB <<< "${VENDOR_DEV[$vid]}"
  if [[ -z "$VENDOR_MOUNT" ]]; then
    echo "ERROR: unknown vendor id '$vid'" >&2
    return 1
  fi
}

# Per-vendor result directory under PROFILE_DIR/results/cross_vendor/
# Usage: vendor_result_dir <test_name> <vendor_id>
vendor_result_dir() {
  local test=$1 vid=$2
  vendor_resolve "$vid" || return 1
  local stamp
  stamp=$(date -u +%Y%m%d_%H%M%S)
  mkdir -p "$PROFILE_DIR/results/cross_vendor/$test/${vid}_${stamp}"
  echo "$PROFILE_DIR/results/cross_vendor/$test/${vid}_${stamp}"
}

# Drop OS page cache before benchmarking.
# Usage: drop_caches
drop_caches() {
  sync >/dev/null 2>&1 || true
  # Try direct write; fall back to sudo. Use || true so set -e does not abort.
  if ! bash -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null; then
    if ! sudo bash -c 'sync; echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null; then
      echo "[drop_caches] WARNING: cannot drop caches; continuing" >&2
    fi
  fi
  return 0
}

# Format a GiB/MiB value into a human-readable string.
# Usage: hr_bytes <bytes>
hr_bytes() {
  awk -v b="$1" 'BEGIN{
    if (b >= 2^30) printf "%.2f GiB", b/2^30;
    else if (b >= 2^20) printf "%.2f MiB", b/2^20;
    else if (b >= 2^10) printf "%.2f KiB", b/2^10;
    else printf "%d B", b;
  }'
}

# Median of a list of numbers (one per line on stdin)
median() {
  sort -n | awk '
    { a[NR]=$1; n++ }
    END {
      if (n==0) { print "nan"; exit }
      if (n%2==1) print a[(n+1)/2]
      else printf "%.1f\n", (a[n/2]+a[n/2+1])/2
    }'
}

# Guard: confirm PROFILE_DIR is set (sourced scripts rely on env)
if [[ -z "${PROFILE_DIR:-}" ]]; then
  export PROFILE_DIR=/home/ficus/llm/storage
fi

export -f vendor_banner vendor_resolve vendor_result_dir drop_caches hr_bytes median