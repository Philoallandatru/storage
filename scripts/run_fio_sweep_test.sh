#!/usr/bin/env bash
# Quick smoke test for the fio sweep pipeline (single run)
set -euo pipefail
RESULTS_BASE="/home/ficus/llm/storage/results/kvcache-profile/fio_sweep"
TEST_FILE="${RESULTS_BASE}/fio_test.dat"
SRC_INI="/home/ficus/llm/storage/results/kvcache-profile/fio_sharegpt_8b_tp8_cpu0p5g_users2_300s_profile_20260608_014520.ini"
mkdir -p "${RESULTS_BASE}"
cd "${RESULTS_BASE}"
truncate -s 5G "${TEST_FILE}"   # small test, just to check pipeline
OUT_INI="smoke_test.ini"
cat "${SRC_INI}" > "${OUT_INI}"
echo "filename=${TEST_FILE}" >> "${OUT_INI}"
echo "runtime=15" >> "${OUT_INI}"
echo "iodepth=32" >> "${OUT_INI}"
echo "iodepth_batch_submit=32" >> "${OUT_INI}"
fio "${OUT_INI}" --output-format=json
echo "=== EXIT CODE: $? ==="