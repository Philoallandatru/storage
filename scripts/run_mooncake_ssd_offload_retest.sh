#!/usr/bin/env bash
#
# Stable Mooncake SSD offload benchmark rerun.
# Runs four configurations and records enough evidence to separate benchmark
# effects from SSD activation failures.
set -euo pipefail

source /home/ficus/llm/.venv/bin/activate

MODEL_PATH="${MODEL_PATH:-/home/ficus/llm/models/Qwen/Qwen3-4B-Instruct-2507}"
BENCH_SCRIPT="${BENCH_SCRIPT:-/home/ficus/llm/infer/ai_ssd_prestudy/sglang_repo/benchmark/hicache/bench_multiturn.py}"
PORT="${PORT:-8189}"
MASTER_ADDR="${MASTER_ADDR:-127.0.0.1:50051}"
OFFLOAD_DIR="${OFFLOAD_DIR:-/mnt/ai_ssd0/mooncake_ssd0/file_storage}"
OUT_ROOT="${OUT_ROOT:-/home/ficus/mooncake_smoke_test/ssd_retest_stable_$(date +%Y%m%d_%H%M%S)}"

# Defaults aim to show the official-style per-turn shape on the local single-GPU
# machine without driving Mooncake into repeated insufficient-space errors.
NUM_CLIENTS="${NUM_CLIENTS:-8}"
NUM_ROUNDS="${NUM_ROUNDS:-8}"
REQUEST_LENGTH="${REQUEST_LENGTH:-4096}"
OUTPUT_LENGTH="${OUTPUT_LENGTH:-1}"
MAX_PARALLEL="${MAX_PARALLEL:-2}"
REQUEST_RATE="${REQUEST_RATE:-8}"
MOONCAKE_SEGMENT_SIZE="${MOONCAKE_SEGMENT_SIZE:-8GB}"
MOONCAKE_SEGMENT_BYTES="${MOONCAKE_SEGMENT_BYTES:-8589934592}"
OFFLOAD_BUFFER_BYTES="${OFFLOAD_BUFFER_BYTES:-1073741824}"
RUN_CONFIGS="${RUN_CONFIGS:-gpu_only,hicache_l1_l2,mooncake_only,mooncake_ssd}"

mkdir -p "$OUT_ROOT" "$OFFLOAD_DIR"

cleanup() {
  pkill -9 -f "sglang.launch_server" 2>/dev/null || true
  pkill -9 -f "mooncake_master" 2>/dev/null || true
  pkill -9 -f "mooncake_client" 2>/dev/null || true
  pkill -9 -f "iostat -dxm" 2>/dev/null || true
  pkill -9 -f "nvidia-smi dmon" 2>/dev/null || true
  sleep 3
}
trap cleanup EXIT

wait_health() {
  local waited=0
  while [ "$waited" -lt 120 ]; do
    if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done
  return 1
}

start_monitors() {
  local out_dir="$1"
  iostat -dxm 1 nvme0n1 nvme1n1 nvme2n1 nvme3n1 > "$out_dir/iostat.log" &
  echo $! > "$out_dir/iostat.pid"
  nvidia-smi dmon -s pucm -d 1 > "$out_dir/dmon.log" &
  echo $! > "$out_dir/dmon.pid"
}

stop_monitors() {
  local out_dir="$1"
  for pid_file in "$out_dir/iostat.pid" "$out_dir/dmon.pid"; do
    if [ -s "$pid_file" ]; then
      kill "$(cat "$pid_file")" 2>/dev/null || true
    fi
  done
}

run_bench() {
  local out_dir="$1"
  python3 "$BENCH_SCRIPT" \
    --model-path "$MODEL_PATH" \
    --host 127.0.0.1 \
    --port "$PORT" \
    --disable-random-sample \
    --output-length "$OUTPUT_LENGTH" \
    --request-length "$REQUEST_LENGTH" \
    --num-clients "$NUM_CLIENTS" \
    --num-rounds "$NUM_ROUNDS" \
    --max-parallel "$MAX_PARALLEL" \
    --request-rate "$REQUEST_RATE" \
    --log-file "$out_dir/bench.log" \
    --tag "$(basename "$out_dir")" \
    --ready-queue-policy random \
    --disable-auto-run \
    --enable-round-barrier \
    2>&1 | tee "$out_dir/bench_stdout.log"
}

collect_common_inventory() {
  local out_dir="$1"
  {
    echo "=== config ==="
    cat "$OUT_ROOT/config.env"
    echo "=== processes ==="
    pgrep -af "sglang.launch_server|mooncake_master|mooncake_client|iostat -dxm|nvidia-smi dmon" || true
    echo "=== offload dir ==="
    echo "$OFFLOAD_DIR"
    find "$OFFLOAD_DIR" -maxdepth 2 -type f -printf '%p %s\n' 2>/dev/null | sort | head -200
    echo "=== du ==="
    du -sh "$OFFLOAD_DIR" 2>/dev/null || true
    echo "=== file count ==="
    find "$OFFLOAD_DIR" -type f 2>/dev/null | wc -l || true
  } > "$out_dir/inventory.log"
}

write_config_json() {
  local path="$1"
  local enable_ssd="$2"
  local ssd_json=null
  if [ "$enable_ssd" = "true" ]; then
    ssd_json="\"$OFFLOAD_DIR\""
  fi
  cat > "$path" <<JSON
{
  "local_hostname": "localhost",
  "metadata_server": "P2PHANDSHAKE",
  "global_segment_size": "$MOONCAKE_SEGMENT_SIZE",
  "protocol": "tcp",
  "device_name": "",
  "master_server_address": "$MASTER_ADDR",
  "master_metrics_port": 9004,
  "check_server": false,
  "standalone_storage": false,
  "enable_ssd_offload": $enable_ssd,
  "ssd_offload_path": $ssd_json
}
JSON
}

start_master() {
  local out_dir="$1"
  local enable_ssd="$2"
  if [ "$enable_ssd" = "true" ]; then
    mooncake_master \
      -enable_offload=true \
      -root_fs_dir="$OFFLOAD_DIR" \
      -metrics_port=9004 \
      -logtostderr \
      2>&1 | tee "$out_dir/master.log" &
  else
    mooncake_master \
      -metrics_port=9004 \
      -logtostderr \
      2>&1 | tee "$out_dir/master.log" &
  fi
  sleep 2
}

launch_server() {
  local config="$1"
  local out_dir="$2"
  local mooncake_config_path="$3"

  case "$config" in
    gpu_only)
      python3 -m sglang.launch_server \
        --model-path "$MODEL_PATH" \
        --host 127.0.0.1 \
        --port "$PORT" \
        --tp 1 \
        --page-size 64 \
        --attention-backend triton \
        2>&1 | tee "$out_dir/server.log" &
      ;;
    hicache_l1_l2)
      python3 -m sglang.launch_server \
        --model-path "$MODEL_PATH" \
        --host 127.0.0.1 \
        --port "$PORT" \
        --tp 1 \
        --page-size 64 \
        --attention-backend triton \
        --enable-hierarchical-cache \
        --hicache-ratio 2 \
        2>&1 | tee "$out_dir/server.log" &
      ;;
    mooncake_only)
      MOONCAKE_MASTER="$MASTER_ADDR" \
      MOONCAKE_GLOBAL_SEGMENT_SIZE="$MOONCAKE_SEGMENT_BYTES" \
      MOONCAKE_PROTOCOL="tcp" \
      SGLANG_HICACHE_MOONCAKE_CONFIG_PATH="$mooncake_config_path" \
      python3 -m sglang.launch_server \
        --model-path "$MODEL_PATH" \
        --host 127.0.0.1 \
        --port "$PORT" \
        --tp 1 \
        --page-size 64 \
        --attention-backend triton \
        --enable-hierarchical-cache \
        --hicache-ratio 2 \
        --hicache-storage-prefetch-policy wait_complete \
        --hicache-mem-layout page_first_direct \
        --hicache-storage-backend mooncake \
        2>&1 | tee "$out_dir/server.log" &
      ;;
    mooncake_ssd)
      MOONCAKE_MASTER="$MASTER_ADDR" \
      MOONCAKE_GLOBAL_SEGMENT_SIZE="$MOONCAKE_SEGMENT_BYTES" \
      MOONCAKE_PROTOCOL="tcp" \
      MOONCAKE_ENABLE_SSD_OFFLOAD=true \
      MOONCAKE_OFFLOAD_FILE_STORAGE_PATH="$OFFLOAD_DIR" \
      MOONCAKE_OFFLOAD_FSDIR="$OFFLOAD_DIR" \
      MOONCAKE_OFFLOAD_LOCAL_BUFFER_SIZE_BYTES="$OFFLOAD_BUFFER_BYTES" \
      MOONCAKE_OFFLOAD_USE_URING=1 \
      SGLANG_HICACHE_MOONCAKE_CONFIG_PATH="$mooncake_config_path" \
      python3 -m sglang.launch_server \
        --model-path "$MODEL_PATH" \
        --host 127.0.0.1 \
        --port "$PORT" \
        --tp 1 \
        --page-size 64 \
        --attention-backend triton \
        --enable-hierarchical-cache \
        --hicache-ratio 2 \
        --hicache-storage-prefetch-policy wait_complete \
        --hicache-mem-layout page_first_direct \
        --hicache-storage-backend mooncake \
        2>&1 | tee "$out_dir/server.log" &
      ;;
    *)
      echo "Unknown config: $config" >&2
      return 2
      ;;
  esac
}

activation_checks() {
  local config="$1"
  local out_dir="$2"
  {
    echo "=== activation checks for $config ==="
    rg -n "Storage root directory|IsEnableOffloading|offload key count|LOCAL_DISK|O_DIRECT|enable_offload|SSD Storage|EVICT|insufficient space|INVALID_KEY|OBJECT_ALREADY_EXISTS|Write page to storage" "$out_dir"/*.log || true
  } > "$out_dir/activation_checks.log"

  if [ "$config" = "mooncake_ssd" ]; then
    if ! rg -q "Storage root directory is:|IsEnableOffloading result: true|offload key count: [1-9]" "$out_dir"/server.log "$out_dir"/master.log; then
      echo "[WARN] SSD activation not proven for $config" | tee -a "$out_dir/activation_checks.log"
    fi
  fi
}

run_one_config() {
  local config="$1"
  local out_dir="$OUT_ROOT/$config"
  local mooncake_config_path="$out_dir/mooncake_config.json"
  mkdir -p "$out_dir"
  cleanup
  rm -rf "${OFFLOAD_DIR:?}/"*

  if [ "$config" = "mooncake_ssd" ]; then
    write_config_json "$mooncake_config_path" true
    start_master "$out_dir" true
  elif [ "$config" = "mooncake_only" ]; then
    write_config_json "$mooncake_config_path" false
    start_master "$out_dir" false
  else
    mooncake_config_path=""
  fi

  start_monitors "$out_dir"
  launch_server "$config" "$out_dir" "$mooncake_config_path"

  if ! wait_health; then
    tail -120 "$out_dir/server.log" >&2 || true
    return 1
  fi

  curl -X POST "http://127.0.0.1:${PORT}/flush_cache" >/dev/null 2>&1 || true
  run_bench "$out_dir"
  stop_monitors "$out_dir"
  collect_common_inventory "$out_dir"
  activation_checks "$config" "$out_dir"
  cleanup
}

cat > "$OUT_ROOT/config.env" <<EOF
MODEL_PATH=$MODEL_PATH
BENCH_SCRIPT=$BENCH_SCRIPT
PORT=$PORT
MASTER_ADDR=$MASTER_ADDR
OFFLOAD_DIR=$OFFLOAD_DIR
NUM_CLIENTS=$NUM_CLIENTS
NUM_ROUNDS=$NUM_ROUNDS
REQUEST_LENGTH=$REQUEST_LENGTH
OUTPUT_LENGTH=$OUTPUT_LENGTH
MAX_PARALLEL=$MAX_PARALLEL
REQUEST_RATE=$REQUEST_RATE
MOONCAKE_SEGMENT_SIZE=$MOONCAKE_SEGMENT_SIZE
MOONCAKE_SEGMENT_BYTES=$MOONCAKE_SEGMENT_BYTES
OFFLOAD_BUFFER_BYTES=$OFFLOAD_BUFFER_BYTES
RUN_CONFIGS=$RUN_CONFIGS
EOF

IFS=',' read -ra CONFIG_LIST <<< "$RUN_CONFIGS"
for config in "${CONFIG_LIST[@]}"; do
  echo "============================================"
  echo "Running config: $config"
  echo "Output: $OUT_ROOT/$config"
  echo "============================================"
  run_one_config "$config"
done

echo "Results: $OUT_ROOT"
