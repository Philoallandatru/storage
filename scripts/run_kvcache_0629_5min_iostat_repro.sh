#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/home/ficus/llm/storage}"
RUN_ROOT="${RUN_ROOT:-/mnt/ai_ssd0/kvcache_0629_5min_iostat_$(date +%Y%m%d_%H%M%S)}"
ARCHIVE_ROOT="${ARCHIVE_ROOT:-${ROOT_DIR}/results/kvcache-profile/0629_5min_iostat_repro_$(date +%Y%m%d_%H%M%S)}"
DEVICE="${DEVICE:-nvme2n1}"
CACHE_ROOT="${RUN_ROOT}/cache"
CONFIG="${CONFIG:-${ROOT_DIR}/kv_cache_benchmark/config.yaml}"
SHAREGPT_PATH="${SHAREGPT_PATH:-${ROOT_DIR}/datasets/sharegpt/ShareGPT_V3_unfiltered_cleaned_split_no_imsorry.json}"
BURSTGPT_PATH="${BURSTGPT_PATH:-${ROOT_DIR}/datasets/BurstGPT/data/BurstGPT_1.csv}"

mkdir -p "${RUN_ROOT}" "${CACHE_ROOT}" "${ARCHIVE_ROOT}"

run_case() {
  local name="$1"
  shift

  local case_dir="${RUN_ROOT}/${name}"
  local cache_dir="${CACHE_ROOT}/${name}"
  mkdir -p "${case_dir}" "${cache_dir}"

  cat > "${case_dir}/metadata.env" <<EOF
source_doc=docs/kv-cache-2026-06-29-test-report.md
config_profile=0629_5min_report
device=${DEVICE}
cache_dir=${cache_dir}
model=llama3.1-8b
num_users=16
duration=300
gpu_mem_gb=0
cpu_mem_gb=0
num_gpus=8
tensor_parallel=8
max_concurrent_allocs=2
generation_mode=none
enable_autoscaling=1
seed=42
EOF

  printf 'Running %s -> %s\n' "${name}" "${case_dir}"
  iostat -dx -m 1 "${DEVICE}" > "${case_dir}/iostat.log" &
  local iostat_pid=$!
  trap 'kill ${iostat_pid} 2>/dev/null || true' EXIT

  set +e
  (
    cd "${ROOT_DIR}"
    uv run python kv_cache_benchmark/kv-cache.py \
      --config "${CONFIG}" \
      --model llama3.1-8b \
      --num-users 16 \
      --duration 300 \
      --gpu-mem-gb 0 \
      --cpu-mem-gb 0 \
      --num-gpus 8 \
      --tensor-parallel 8 \
      --max-concurrent-allocs 2 \
      --generation-mode none \
      --enable-autoscaling \
      --cache-dir "${cache_dir}" \
      --seed 42 \
      --output "${case_dir}/result.json" \
      "$@"
  ) > "${case_dir}/run.log" 2>&1
  local rc=$?
  set -e

  kill "${iostat_pid}" 2>/dev/null || true
  wait "${iostat_pid}" 2>/dev/null || true
  trap - EXIT
  printf '%s\n' "${rc}" > "${case_dir}/exit_code"
  mkdir -p "${ARCHIVE_ROOT}/${name}"
  cp -a "${case_dir}/." "${ARCHIVE_ROOT}/${name}/"
  rm -rf "${cache_dir}"
  df -h "$(dirname "${RUN_ROOT}")" > "${case_dir}/df_after_cleanup.txt" || true
  cp -a "${case_dir}/df_after_cleanup.txt" "${ARCHIVE_ROOT}/${name}/df_after_cleanup.txt" || true
  if [[ "${rc}" -ne 0 ]]; then
    printf 'Case %s failed with rc=%s; see %s\n' "${name}" "${rc}" "${case_dir}/run.log" >&2
    return "${rc}"
  fi
}

run_case burstgpt_0629_5min \
  --use-burst-trace \
  --burst-trace-path "${BURSTGPT_PATH}" \
  --trace-speedup 1000

run_case sharegpt_0629_5min \
  --dataset-path "${SHAREGPT_PATH}" \
  --max-conversations 5000

printf 'RUN_ROOT=%s\n' "${RUN_ROOT}"
printf 'ARCHIVE_ROOT=%s\n' "${ARCHIVE_ROOT}"
