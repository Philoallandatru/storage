#!/usr/bin/env bash
# AI SSD 4-盘快速差异测试 — 基于 sharegpt/burstgpt/default IO 模式
# 总时长: ~5 分钟
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR"

DISKS=("/mnt/ai_ssd0" "/mnt/ai_ssd1" "/mnt/ai_ssd2" "/tmp/ai_ssd3_test")
LABELS=("WDC_894G" "SEAGATE_932G" "ZHITAI_932G" "BIWIN_383G")
OUTDIR="results/ai-ssd-quick-test-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTDIR"

FIO_JOB="$SCRIPT_DIR/ai_ssd_fio_quick_test.fio"
[[ -f "$FIO_JOB" ]] || { echo "ERROR: $FIO_JOB not found"; exit 1; }

# 检查挂载
for d in "${DISKS[@]}"; do
    base="${d%/test}"  # strip test dir
    if [[ "$d" == /tmp/* ]]; then
        mkdir -p "$d"
    elif ! mountpoint -q "$d"; then
        echo "ERROR: $d not mounted"; exit 1
    fi
done

TOTAL_START=$(date +%s)

for i in 0 1 2 3; do
    DISK="${DISKS[$i]}"
    LABEL="${LABELS[$i]}"
    echo "===== [$LABEL] $DISK ====="

    # 1. 准备测试文件 (1GiB = fio size 设置)
    PREP_FILE="$DISK/test.bin"
    echo "  creating 1GiB test file..."
    sudo fio --name=prep --filename="$PREP_FILE" --size=1G \
             --rw=write --bs=1M --ioengine=libaio --iodepth=4 \
             --runtime=10 --time_based=0 > /dev/null 2>&1

    # 2. 清空 page cache
    sync
    sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
    echo "  page cache cleared"

    # 3. 跑 fio job
    OUT="$OUTDIR/${LABEL}.json"
    echo "  running fio..."
    sudo fio "$FIO_JOB" \
        --output-format=json \
        --output="$OUT" \
        --filename="$PREP_FILE" 2>&1

    # 4. 删测试文件
    echo "  cleaning..."
    sudo rm -f "$PREP_FILE"

    echo "  saved $OUT"
    echo ""
done

TOTAL_END=$(date +%s)
echo "===== TOTAL TIME: $((TOTAL_END - TOTAL_START))s ====="
echo "===== RESULTS DIR: $OUTDIR ====="
ls -la "$OUTDIR"
