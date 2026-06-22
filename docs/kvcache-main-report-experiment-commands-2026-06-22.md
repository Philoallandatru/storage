# KV Cache 主要报告实验命令索引

日期: 2026-06-22

本文汇总 AI SSD / KV Cache 主要报告实验中的可复现命令，并解释关键参数。范围覆盖 2026-06-08 到 2026-06-13 归档报告中的主线实验: BurstGPT baseline、4 层 profiling、saturation、prefill/decode 拆分、fio iodepth sweep、SSD preconditioning、page cache sensitivity、长稳态、跨盘 K1-K5/K4/K5/pressure 测试。

相关主报告:

| 报告 | 覆盖内容 |
|---|---|
| `docs/kvcache-full-profiling-results-2026-06-08.md` | 4 层 profiling 主数据 |
| `docs/kvcache-fio-iodepth-sweep-2026-06-08.md` | fio iodepth sweep |
| `docs/kvcache-ssd-preconditioning-2026-06-08.md` | SSD preconditioning |
| `docs/kvcache-pagecache-sensitivity-2026-06-09.md` | page cache sensitivity |
| `docs/kvcache-long-steady-state-2026-06-09.md` | 30min 长稳态 |
| `docs/kvcache-saturation-points-2026-06-08.md` | 8B/70B saturation |
| `docs/ai-ssd-kvcache-complete-archive-report-2026-06-13.md` | 完整实验归档 |
| `docs/kv-cache-final-selection-2026-06-10.md` | 跨盘 KV Cache 选型 |

## 1. 通用运行环境

大多数实验先进入仓库、激活虚拟环境，再进入 KV Cache benchmark 子目录:

```bash
cd /home/ficus/llm/storage
source .venv/bin/activate
cd kv_cache_benchmark
```

通用路径:

| 路径 | 用途 |
|---|---|
| `/home/ficus/llm/storage/kv_cache_benchmark/kv-cache.py` | MLPerf Storage KV Cache benchmark 入口 |
| `/home/ficus/llm/storage/kv_cache_benchmark/config.yaml` | benchmark 配置 |
| `/home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv` | BurstGPT trace |
| `/home/ficus/llm/storage/results/kvcache-profile` | 单盘 KV Cache 结果 |
| `/home/ficus/llm/storage/results/cross_vendor` | 跨盘结果 |

## 2. KV Cache benchmark 核心命令

这是多数实验脚本内部最终调用的核心命令形态:

```bash
python3 kv-cache.py \
  --config config.yaml \
  --model llama3.1-70b-instruct \
  --num-users 6 \
  --duration 300 \
  --gpu-mem-gb 0 \
  --cpu-mem-gb 0 \
  --num-gpus 8 \
  --tensor-parallel 8 \
  --max-concurrent-allocs 2 \
  --generation-mode none \
  --use-burst-trace \
  --burst-trace-path /home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv \
  --trace-speedup 1000 \
  --replay-cycles 0 \
  --cache-dir /home/ficus/llm/storage/results/kvcache-profile/kv-cache-dir-<run_id> \
  --seed 42 \
  --output /home/ficus/llm/storage/results/kvcache-profile/test_<run_id>.json \
  --xlsx-output /home/ficus/llm/storage/results/kvcache-profile/test_<run_id>.xlsx
```

关键参数:

| 参数 | 含义 | 本轮实验中的用法 |
|---|---|---|
| `--config` | benchmark 配置文件 | 固定使用 `config.yaml` |
| `--model` | 模型规格，决定 KV object 大小 | 常用 `llama3.1-8b`、`llama3.1-70b-instruct` |
| `--num-users` | 并发用户数 | 2/4/6/8 用于 baseline，12/16/32 用于 saturation/pressure |
| `--duration` | 运行时长，单位秒 | 120/180/300/600/900/1200/1800 |
| `--gpu-mem-gb` | 模拟 GPU tier 容量 | `0` 表示强制绕过 GPU tier，放大 SSD 压力 |
| `--cpu-mem-gb` | 模拟 CPU DRAM tier 容量 | `0` 表示强制落 SSD；pressure 测试用 `80` 验证真实 tier cascade |
| `--num-gpus` | 模拟 GPU 数量 | 固定 `8` |
| `--tensor-parallel` | Tensor parallel 切分数 | 固定 `8`，单 rank KV object 约为 TP1 的 1/8 |
| `--max-concurrent-allocs` | 同时分配 KV cache 的上限 | 早期主线固定 `2` 防止内存爆；pressure 测试移除此限制 |
| `--generation-mode none` | 不执行真实文本生成 | 只测 KV cache 存储路径 |
| `--use-burst-trace` | 使用 BurstGPT trace | 主线生产类压力测试均启用 |
| `--burst-trace-path` | BurstGPT CSV 路径 | 固定为 `BurstGPT_1.csv` |
| `--trace-speedup` | 压缩 trace 时间轴 | `1000` 用于压测；pressure 修正版用 `10` 减少过度压缩 |
| `--replay-cycles` | trace 重放轮数 | `0` 表示按 duration 截断；pressure 用 `1` 做完整重放 |
| `--cache-dir` | KV cache 落盘目录 | 通常是临时目录，跑完删除，只保留 JSON/XLSX/log |
| `--seed` | 随机种子 | 固定 `42`，便于复现 |
| `--output` | JSON 结果 | benchmark 主要结构化结果 |
| `--xlsx-output` | Excel 结果 | 面向报告检查和人工查看 |

## 3. BurstGPT 70B users=6 基线补点

入口脚本:

```bash
bash scripts/run_70b_users6.sh
```

用途:

| 项 | 说明 |
|---|---|
| 目标 | 补齐 70B users=6 中间点 |
| 模型 | `llama3.1-70b-instruct` |
| 并发 | `--num-users 6` |
| 时长 | `--duration 300` |
| tier | `--gpu-mem-gb 0 --cpu-mem-gb 0`，纯 SSD 压力 |
| trace | BurstGPT + `--trace-speedup 1000` |
| 产物 | `results/kvcache-profile/test_burstgpt_70b_tp8_cpu0g_users6_*.json/.xlsx` |

## 4. 4 层 profiling 主实验

入口脚本:

```bash
bash scripts/run_full_profiling.sh burstgpt_70b_users6_full llama3.1-70b-instruct 6 300
bash scripts/run_full_profiling.sh burstgpt_70b_users8_full llama3.1-70b-instruct 8 300
bash scripts/run_full_profiling.sh burstgpt_8b_users8_full llama3.1-8b 8 300
```

脚本参数位置:

```bash
bash scripts/run_full_profiling.sh <config-name> [model] [users] [duration]
```

| 位置参数 | 含义 | 示例 |
|---|---|---|
| `<config-name>` | run id 前缀，用于命名目录和结果文件 | `burstgpt_70b_users6_full` |
| `[model]` | 模型 | `llama3.1-70b-instruct` |
| `[users]` | 并发用户数 | `6` |
| `[duration]` | 每轮时长 | `300` |

脚本内部会跑两轮:

### Round 1: trace 模式

```bash
python3 kv-cache.py --config config.yaml \
  --model "${MODEL}" \
  --num-users "${USERS}" \
  --duration "${DURATION}" \
  --gpu-mem-gb 0 --cpu-mem-gb 0 \
  --num-gpus 8 --tensor-parallel 8 \
  --max-concurrent-allocs 2 \
  --generation-mode none \
  --use-burst-trace \
  --burst-trace-path /home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv \
  --trace-speedup 1000 \
  --replay-cycles 0 \
  --cache-dir "${CACHE_DIR}" \
  --seed 42 \
  --io-trace-log "${LOG_DIR}/kv_trace.csv.zst" \
  --enable-autoscaling \
  --log-level INFO \
  --output "${PROFILE_DIR}/test_${RUN_ID}_trace.json" \
  --xlsx-output "${PROFILE_DIR}/test_${RUN_ID}_trace.xlsx"
```

新增参数:

| 参数 | 含义 | 注意 |
|---|---|---|
| `--io-trace-log` | 输出 L3 filesystem/KV I/O trace | 启用后使用 NullBackend，适合分析 workload shape，不适合看真实硬件延迟 |
| `--enable-autoscaling` | 启用 benchmark 自动扩展负载 | saturation 实验会让 users 扩到更高，容量规划需看 real I/O 轮 |
| `--log-level INFO` | 输出更完整日志 | 便于报告追溯 |

### Round 2: 真实硬件 I/O + latency tracing

```bash
python3 kv-cache.py --config config.yaml \
  --model "${MODEL}" \
  --num-users "${USERS}" \
  --duration "${DURATION}" \
  --gpu-mem-gb 0 --cpu-mem-gb 0 \
  --num-gpus 8 --tensor-parallel 8 \
  --max-concurrent-allocs 2 \
  --generation-mode none \
  --use-burst-trace \
  --burst-trace-path /home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv \
  --trace-speedup 1000 \
  --replay-cycles 0 \
  --cache-dir "${CACHE_DIR2}" \
  --seed 42 \
  --enable-latency-tracing \
  --enable-autoscaling \
  --log-level INFO \
  --output "${PROFILE_DIR}/test_${RUN_ID}_hwio.json" \
  --xlsx-output "${PROFILE_DIR}/test_${RUN_ID}_hwio.xlsx"
```

新增参数:

| 参数 | 含义 | 注意 |
|---|---|---|
| `--enable-latency-tracing` | 启用 bpftrace/block 层 latency stack | 需要 `bpftrace` 和可用 sudo；输出 Q2D/D2C、bssplit、fio workload |
| 没有 `--io-trace-log` | 让 I/O 真正落到硬件 | 这是判断真实 device P95/P99 的关键 |

后台采样命令:

```bash
iostat -dx -m 1 > "${LOG_DIR}/iostat.log" 2>&1 &
pidstat -d -r -s -u 1 > "${LOG_DIR}/pidstat.log" 2>&1 &
sudo -n perf stat -e cache-misses,cache-references,cs,migrations,page-faults \
  sleep "${DURATION}" > "${LOG_DIR}/perf.log" 2>&1 &
```

| 命令 | 数据层级 | 作用 |
|---|---|---|
| `iostat -dx -m 1` | L1 device | 每秒采集 NVMe IOPS、BW、await、util |
| `pidstat -d -r -s -u 1` | L1 process | 每秒采集进程 I/O、内存、CPU |
| `perf stat ... sleep` | CPU counters | 采集 cache miss、context switch、migration、page fault |

## 5. Saturation 边界实验

入口命令:

```bash
bash scripts/run_full_profiling.sh burstgpt_70b_tp8_cpu0g_users12 llama3.1-70b-instruct 12 300
bash scripts/run_full_profiling.sh burstgpt_8b_tp8_cpu0g_users32 llama3.1-8b 32 300
```

用途:

| 配置 | 目标 |
|---|---|
| 70B users=12 | 找 70B 在 users8 之后的服务级饱和点 |
| 8B users=32 | 找小模型高并发的服务级饱和点 |

解读要点:

| 指标 | 为什么重要 |
|---|---|
| benchmark JSON 中的 E2E P95 | 判断服务是否已经排队不可用 |
| read/write device P95 | 判断 SSD/object 路径是否先饱和 |
| iostat util/await | 判断设备层是否真的满载 |
| trace mode 结果 | 只用于 workload shape，不能用于容量规划 |

## 6. Prefill-only / Decode-only 拆分实验

入口命令:

```bash
bash scripts/run_prefill_decode_sweep.sh
```

脚本内部分别跑:

```bash
--prefill-only
--decode-only
```

核心命令形态:

```bash
python3 kv-cache.py --config config.yaml \
  --model llama3.1-70b-instruct \
  --num-users 6 \
  --duration 300 \
  --gpu-mem-gb 0 --cpu-mem-gb 0 \
  --num-gpus 8 --tensor-parallel 8 \
  --max-concurrent-allocs 2 \
  --generation-mode none \
  --use-burst-trace \
  --burst-trace-path /home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv \
  --trace-speedup 1000 \
  --replay-cycles 0 \
  --cache-dir "${CACHE_DIR}" \
  --seed 42 \
  --io-trace-log "${LOG_DIR}/kv_trace.csv.zst" \
  --prefill-only \
  --output "${PROFILE_DIR}/test_${RUN_ID}_trace.json"
```

第二轮把 `--io-trace-log` 换成 `--enable-latency-tracing`，并把 `--prefill-only` 换成 `--decode-only`。

| 参数 | 含义 |
|---|---|
| `--prefill-only` | 只测 prompt/prefill 阶段，主要放大写路径 |
| `--decode-only` | 只测 generation/decode 阶段，主要放大读路径 |

## 7. fio iodepth sweep

入口命令:

```bash
bash scripts/run_fio_sweep.sh
```

分析命令:

```bash
source /home/ficus/llm/storage/.venv/bin/activate
python3 /home/ficus/llm/storage/scripts/analyze_fio_sweep.py
```

单个 fio 复现示例:

```bash
cd /home/ficus/llm/storage/results/kvcache-profile/fio_sweep
fio sharegpt_8b_cpuhalf_qd32/fio_sweep.ini --output-format=json
```

脚本核心逻辑:

```bash
IODEPTHS=(32 64 128 256 1024)
RUNTIME=60

fio "${OUT_INI}" --output-format=json > "${RUN_DIR}/fio_output.json" 2> "${RUN_DIR}/fio_stderr.txt"
python3 /home/ficus/llm/storage/scripts/parse_fio_json.py "${RUN_DIR}/fio_output.json"
```

输入 workload:

| workload | 来源 INI | 读写特征 |
|---|---|---|
| `sharegpt_8b_cpuhalf` | `fio_sharegpt_8b_tp8_cpu0p5g_users2_300s_profile_20260608_014520.ini` | 约 61% read |
| `burstgpt_8b_cpurel_spd1000` | `fio_burstgpt_8b_tp8_cpu0g_users2_300s_speedup1000_profile_20260608_070000.ini` | 约 91% read |
| `tp8_cpuhalf_generic` | `fio_tp8_cpu0p5g_300s_profile_20260607_183517.ini` | 约 73% read |

关键 fio 参数:

| 参数 | 含义 | 本实验设置 |
|---|---|---|
| `iodepth` | fio 队列深度 | 扫 `32/64/128/256/1024` |
| `iodepth_batch_submit` | 每次批量提交 I/O 数 | 跟随 `iodepth` |
| `runtime` | 单次运行时长 | `60s` |
| `filename` | 测试文件 | `fio_test.dat` |
| `--output-format=json` | JSON 输出 | 便于脚本抽取 P50/P95/P99/IOPS/BW |

注意: bpftrace 蒸馏出的超大 `iodepth` 如 524288/1048576 是系统侧 in-flight 堆积信号，不应直接作为裸盘产品测试参数。本轮报告用 sweep 找到更合理的 qd，结论约为 `qd=32`。

## 8. SSD preconditioning + fio sweep

完整入口:

```bash
bash scripts/run_fio_sweep_preconditioned.sh
```

如果 SSD 已经预写满，只跑后续 6 个 fio case:

```bash
bash scripts/run_fio_sweep_precond_only.sh
```

预处理核心命令:

```bash
fio --name=precondition \
  --filename="${PRECOND_FILE}" \
  --rw=write \
  --bs=128k \
  --size=100G \
  --runtime=600 \
  --time_based \
  --ioengine=libaio \
  --iodepth=32 \
  --direct=1 \
  --numjobs=1 \
  --group_reporting \
  --output-format=json,normal \
  > precondition.json 2>&1
```

关键参数:

| 参数 | 含义 |
|---|---|
| `--rw=write` | 顺序写预处理文件，推动 SSD 进入稳态 |
| `--bs=128k` | 128KiB block size，贴近 KV Cache 蒸馏 workload 的主块大小 |
| `--size=100G` | 预处理文件大小 |
| `--runtime=600 --time_based` | 以时间为准持续写，写完 size 后可循环 |
| `--direct=1` | 绕过 page cache，测真实设备 |
| `--iodepth=32` | 使用前面 sweep 得出的合理队列深度 |

后续 fio sweep 只跑缩减矩阵:

| 维度 | 设置 |
|---|---|
| workload | 3 个蒸馏 workload |
| iodepth | `32` 和 `1024` |
| runtime | 每个 60s |
| 输出 | `results/kvcache-profile/fio_sweep_precond/sweep_precond_summary.csv` |

## 9. Page cache sensitivity sweep

入口命令:

```bash
bash scripts/pagecache_sensitivity_sweep.sh
```

可选环境变量:

```bash
DURATION=120 TEST_FILE_SIZE_GB=40 bash scripts/pagecache_sensitivity_sweep.sh
```

测试矩阵:

| cell | memory.max | 额外设置 | 目的 |
|---|---:|---|---|
| `dram_unlimited` | `max` | 默认 page cache | 无内存限制基线 |
| `dram_32gb` | 32GiB | cgroup v2 memory limit | 中等 DRAM 限制 |
| `dram_8gb` | 8GiB | cgroup v2 memory limit | 强 DRAM 限制 |
| `dram_8gb_evict` | 8GiB | fio `invalidate=1` | 强制 page cache miss 的 worst case |

脚本核心处理:

```bash
sudo "${WORKER}" "${label}" "${mem_max}" "${test_file}" "${SOURCE_JSON}" "${DURATION}" "${TEST_FILE_SIZE_GB}" "${run_dir}"
```

worker 内部会:

```bash
echo "${MEM_MAX}" > "${CGROUP_PATH}/memory.max"
sync
echo 3 > /proc/sys/vm/drop_caches
iostat -dx -m 1 > "${RUN_DIR}/iostat.log" 2>&1 &
fio "${FIO_INI}" > "${RUN_DIR}/fio.log" 2>&1
```

关键参数/行为:

| 项 | 含义 |
|---|---|
| `direct=0` | 使用 buffered I/O，让 page cache 参与 |
| `ioengine=psync` | buffered I/O 下使用同步路径 |
| `iodepth=32` | 将蒸馏 workload 的超大 qd 降为合理 qd |
| `invalidate=1` | 每次 I/O 后丢弃 page cache，用于模拟持续 cache miss |
| `memory.max` | cgroup 内存上限；注意 cgroup v2 不总是限制共享 kernel page cache |
| `drop_caches` | 每个 cell 前清 page cache，降低上一个 cell 的污染 |

## 10. 30min 长稳态 KV Cache

入口命令:

```bash
bash scripts/run_long_steady_state.sh 30
```

参数:

| 参数 | 含义 |
|---|---|
| `30` | 运行分钟数；脚本转为 `duration=1800s` |

内部 benchmark:

```bash
python3 kv-cache.py --config config.yaml \
  --model llama3.1-70b-instruct \
  --num-users 6 \
  --duration 1800 \
  --gpu-mem-gb 0 --cpu-mem-gb 0 \
  --num-gpus 8 --tensor-parallel 8 \
  --max-concurrent-allocs 2 \
  --generation-mode none \
  --use-burst-trace \
  --burst-trace-path /home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv \
  --trace-speedup 1000 \
  --replay-cycles 0 \
  --cache-dir "${CACHE_DIR}" \
  --seed 42 \
  --enable-latency-tracing \
  --enable-autoscaling \
  --output "${BENCH_OUT}" \
  --xlsx-output "${BENCH_XLSX}"
```

用途:

| 目标 | 说明 |
|---|---|
| GC drift | 观察 30min 内 await/util 是否随时间恶化 |
| SLC cache 行为 | 判断短时跑分是否受 SLC cache 美化 |
| 稳态服务风险 | 比 300s benchmark 更接近产品风险 |

## 11. 跨盘 K2-K5 矩阵

入口命令:

```bash
bash scripts/cross_vendor_kv_cache_k2_k5.sh
```

测试矩阵:

| scenario | users | model | duration | 目标 |
|---|---:|---|---:|---|
| `K2` | 4 | `llama3.1-8b` | 120s | 轻中等 8B |
| `K3` | 8 | `llama3.1-8b` | 120s | 中等 8B |
| `K4` | 16 | `llama3.1-8b` | 120s | 高并发 8B |
| `K5` | 4 | `llama3.1-70b-instruct` | 180s | 70B 大 object |

跨盘列表:

```bash
VENDORS=(wd_sn570 biwin_x570 zhitai_ti600 seagate_fc530)
```

内部 benchmark 特征:

```bash
python3 "$KV_BENCH_DIR/kv-cache.py" \
  --config "$KV_BENCH_DIR/config.yaml" \
  --model "$model" \
  --num-users "$users" \
  --duration "$duration" \
  --gpu-mem-gb 0 \
  --cpu-mem-gb 0 \
  --num-gpus 8 \
  --tensor-parallel 8 \
  --max-concurrent-allocs 2 \
  --generation-mode none \
  --use-burst-trace \
  --burst-trace-path "$BURST_TRACE" \
  --trace-speedup 1000 \
  --replay-cycles 0 \
  --cache-dir "$cache_dir" \
  --seed 42 \
  --output "kv_cache_summary.json" \
  --log-level WARNING > kv_cache.log 2>&1
```

每个盘同时采:

```bash
iostat -dx -m 1 > iostat.txt 2>&1 &
```

结果目录:

```text
results/cross_vendor/kv_cache/<vendor>/<scenario>_<users>u_<model>_<duration>s/
```

## 12. 跨盘 K4 GC drift 长稳态

20min 版本:

```bash
bash scripts/cross_vendor_kv_cache_k4_gc_drift.sh
```

30min/按盘容量裁剪版本:

```bash
bash scripts/cross_vendor_kv_cache_k4_30min_drift.sh
```

K4 GC drift 固定 benchmark:

```bash
python3 "$KV_BENCH_DIR/kv-cache.py" \
  --config "$KV_BENCH_DIR/config.yaml" \
  --model llama3.1-8b \
  --num-users 16 \
  --duration "$DURATION" \
  --gpu-mem-gb 0 \
  --cpu-mem-gb 0 \
  --num-gpus 8 \
  --tensor-parallel 8 \
  --max-concurrent-allocs 2 \
  --generation-mode none \
  --use-burst-trace \
  --burst-trace-path "$BURST_TRACE" \
  --trace-speedup 1000 \
  --replay-cycles 0 \
  --cache-dir "$cache_dir" \
  --seed 42 \
  --output kv_cache_summary.json \
  --log-level WARNING > kv_cache.log 2>&1
```

30min 版本按盘设置:

| vendor | duration |
|---|---:|
| `biwin_x570` | 1800s |
| `seagate_fc530` | 1800s |
| `zhitai_ti600` | 900s |
| `wd_sn570` | 900s |

用途:

| 目标 | 说明 |
|---|---|
| 长时间写入后的 GC cliff | K4 持续写入量大，能暴露消费级 SSD 后段风险 |
| 跨盘稳定性 | 比短测 K2-K5 更能支撑最终选型 |
| iostat 时间序列 | 用 first/last window 比较 drift |

## 13. 跨盘 K5-only 70B 对比

入口命令:

```bash
bash scripts/cross_vendor_kv_cache_k5_only.sh
```

固定配置:

| 参数 | 值 |
|---|---|
| model | `llama3.1-70b-instruct` |
| users | `4` |
| duration | `180s` |
| GPU/CPU tier | `0/0` |
| TP | `8` |
| trace speedup | `1000` |

用途:

| 目标 | 说明 |
|---|---|
| 70B 大 object 跨盘比较 | K4 是 8B 高并发，K5 补 70B 大对象压力 |
| 验证短时 baseline | 用同一参数在 4 盘串行跑，减少方法差异 |

## 14. 跨盘 pressure 修正版

入口命令:

```bash
bash scripts/cross_vendor_kv_cache_pressure.sh
```

测试盘:

```bash
VENDORS=(biwin_x570 zhitai_ti600 seagate_fc530)
```

跳过 WD，因为早期已经验证为慢盘。

pressure 场景:

| scenario | users | model | duration | 目标 |
|---|---:|---|---:|---|
| `P1` | 16 | `llama3.1-70b-instruct` | 300s | 大模型 + 高并发，放大写尾差异 |
| `P2` | 8 | `llama3.1-8b` | 600s | 较长时长，观察 GC 参与 |

关键修正参数:

```bash
SHARED_ARGS=(
  --gpu-mem-gb 80
  --cpu-mem-gb 80
  --num-gpus 8
  --tensor-parallel 8
  --generation-mode none
  --use-burst-trace
  --trace-speedup 10
  --replay-cycles 1
  --storage-capacity-gb 200
  --seed 42
  --log-level WARNING
)
```

与早期 K1-K5 的关键区别:

| 参数 | K1-K5 | pressure 修正版 | 意义 |
|---|---|---|---|
| `--gpu-mem-gb` | `0` | `80` | 模拟真实 GPU tier |
| `--cpu-mem-gb` | `0` | `80` | 模拟真实 DRAM tier |
| `--trace-speedup` | `1000` | `10` | 避免把 33h trace 过度压缩 |
| `--max-concurrent-allocs` | `2` | 不设置 | 避免人为压低并发 |
| `--storage-capacity-gb` | 不设置 | `200` | 限制 cache 容量，触发更真实 eviction |
| `--replay-cycles` | `0` | `1` | 完整跑一轮 trace |

## 15. 结果分析常用命令

fio sweep:

```bash
python3 scripts/analyze_fio_sweep.py
```

long steady-state:

```bash
python3 scripts/analyze_long_steady_state.py \
  --iostat-log <profiling_run>/iostat.log \
  --out-dir <analysis_dir>
```

page cache:

```bash
python3 scripts/analyze_pagecache_sensitivity.py
```

cross-vendor KV iostat:

```bash
python3 scripts/analyze_kv_cache_iostat.py
```

这些分析脚本通常读取 `iostat.log`/`iostat.txt`、fio JSON/log、benchmark JSON，并生成 CSV、Markdown、PNG 或 JSON 摘要。

## 16. 参数选择的报告级解释

| 参数/设计 | 为什么这样选 |
|---|---|
| `gpu_mem=0, cpu_mem=0` | 强制 KV cache 落 SSD，放大盘间差异，适合 AI SSD 压测 |
| `tensor_parallel=8` | 贴近多 GPU 推理配置，同时降低单 rank KV object 大小 |
| `trace-speedup=1000` | 快速把 BurstGPT 生产 trace 压缩到 120-300s 内，适合压力放大 |
| `trace-speedup=10` | pressure 修正版更接近生产时间分布，避免过度压缩导致不真实 |
| `max-concurrent-allocs=2` | 早期为防止 RAM 爆炸和保持 Codex 历史数据一致 |
| 移除 `max-concurrent-allocs` | pressure 修正版为了恢复真实并发 |
| `--io-trace-log` 单独一轮 | trace mode 使用 NullBackend，适合分析 workload，不适合看真实延迟 |
| `--enable-latency-tracing` 单独一轮 | 真实 I/O + bpftrace，适合看块层和设备层延迟 |
| `iostat -dx -m 1` | 1 秒粒度足够看 await/util drift 和设备饱和 |
| `fio iodepth sweep` | 蒸馏出的巨大 qd 不是产品可用参数，必须扫真实 qd |
| `preconditioning` | 排除空盘/SLC cache 偏乐观，观察稳态行为 |
| `page cache direct=0` | 只有 buffered I/O 才能测试 page cache 对 KV-like workload 的影响 |
| `direct=1` in fio sweep | 绕过 page cache，测 SSD 原生设备路径 |

## 17. 最小复现路径

如果只想复现主报告的核心结论，推荐按这个顺序跑:

```bash
# 1. 4 层 profiling: 70B users=6 主基线
bash scripts/run_full_profiling.sh burstgpt_70b_users6_full llama3.1-70b-instruct 6 300

# 2. 70B users=8，接近边界
bash scripts/run_full_profiling.sh burstgpt_70b_users8_full llama3.1-70b-instruct 8 300

# 3. saturation: 70B users=12
bash scripts/run_full_profiling.sh burstgpt_70b_tp8_cpu0g_users12 llama3.1-70b-instruct 12 300

# 4. prefill/decode 拆分
bash scripts/run_prefill_decode_sweep.sh

# 5. fio 真实 iodepth sweep
bash scripts/run_fio_sweep.sh

# 6. 长稳态
bash scripts/run_long_steady_state.sh 30
```

跨盘选型最小复现:

```bash
# 短测矩阵
bash scripts/cross_vendor_kv_cache_k2_k5.sh

# 长稳态 K4 drift
bash scripts/cross_vendor_kv_cache_k4_30min_drift.sh

# 70B K5 跨盘复核
bash scripts/cross_vendor_kv_cache_k5_only.sh
```

