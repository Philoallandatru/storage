# DGX Spark 128GB KV Cache 盘压测试方案

日期: 2026-06-23

本文说明如何在 128GB 级别 VRAM/DRAM 资源的 DGX Spark 上测试不同 SSD 的 KV cache 压力。目标是同时得到两类结论:

1. 真实 DGX Spark tiering 下，各盘从什么负载开始影响 KV cache。
2. 在排除 GPU/DRAM 缓冲后，各盘的纯 SSD KV cache 压力排序和长稳态风险。

本文配套脚本:

```bash
scripts/dgx_spark_kvcache_sweep.sh
```

## 1. 基本假设

默认假设 DGX Spark 可给 KV cache 使用的 GPU/CPU 内存合计约 128GB。为了保守，本方案主测试用:

```bash
--gpu-mem-gb 32
--cpu-mem-gb 32
```

也就是只给 KV cache 约 64GB 热数据空间，剩余内存留给模型权重、runtime、系统和其他服务。如果你的机器实际是 VRAM 128GB + DRAM 128GB 两层各 128GB，可以把主档放大到:

```bash
--gpu-mem-gb 64
--cpu-mem-gb 64
```

DGX Spark 更接近单机单 GPU / 统一内存形态，因此建议使用:

```bash
--num-gpus 1
--tensor-parallel 1
```

不要直接沿用 8 卡报告里的:

```bash
--num-gpus 8
--tensor-parallel 8
```

TP 会改变单 rank KV object 大小。要比较 DGX Spark 上的盘压，应优先用 TP1。

## 2. 推荐测试组合

| 优先级 | 测试 | 目的 | 是否作为主结论 |
|---|---|---|---|
| P0 | realistic tiering users sweep | 最贴近 DGX Spark 真实 KV cache 压力 | 是 |
| P0 | long steady-state | 看 GC、SLC cache、写尾和 drift | 是 |
| P1 | pure SSD pressure | 排除内存缓冲，拉开盘间差异 | 否，作为盘能力排序 |
| P1 | fio distilled sweep | 解释设备层瓶颈 | 否，作为底层佐证 |
| P2 | page cache sensitivity | 判断 Linux page cache 是否掩盖盘压 | 视需要 |

报告主结论应来自 `realistic` + `long`。`pure` 和 fio 更适合做附录，解释为什么某块盘差。

## 3. 测试矩阵

### 3.1 Realistic tiering 主测试

参数:

```bash
--gpu-mem-gb 32
--cpu-mem-gb 32
--num-gpus 1
--tensor-parallel 1
--trace-speedup 10
--replay-cycles 1
--storage-capacity-gb 200
```

矩阵:

| 模型 | users | duration | 目的 |
|---|---:|---:|---|
| `llama3.1-70b-instruct` | 1, 2, 4, 8 | 600s | 大模型大 KV object 压力 |
| `llama3.1-8b` | 8, 16, 32 | 600s | 小模型高并发压力 |

解释:

| 参数 | 原因 |
|---|---|
| `trace-speedup=10` | 比 1000 更接近真实生产 trace 时间分布 |
| `replay-cycles=1` | 完整重放一轮 trace，避免只截取短片段 |
| 不设置 `--max-concurrent-allocs` | 避免人为压低并发 |
| `storage-capacity-gb=200` | 限制 cache 容量，触发更真实 eviction |

### 3.2 Pure SSD pressure 排序测试

参数:

```bash
--gpu-mem-gb 0
--cpu-mem-gb 0
--trace-speedup 1000
--replay-cycles 0
--max-concurrent-allocs 2
```

矩阵:

| 模型 | users | duration | 目的 |
|---|---:|---:|---|
| `llama3.1-70b-instruct` | 4 | 300s | 大对象纯 SSD 压力 |
| `llama3.1-8b` | 16 | 300s | 高并发纯 SSD 压力 |

解释:

这组测试不是 DGX Spark 真实服务结论。它的价值是把所有数据强制落 SSD，从而更快暴露盘间差异、写尾和 object-level latency。

### 3.3 Long steady-state 长稳态

参数沿用 realistic tiering:

```bash
--gpu-mem-gb 32
--cpu-mem-gb 32
--num-gpus 1
--tensor-parallel 1
--trace-speedup 10
--replay-cycles 1
```

矩阵:

| 模型 | users | duration | 目的 |
|---|---:|---:|---|
| `llama3.1-8b` | 16 | 1800s | 高并发长时间写入，观察 GC drift |
| `llama3.1-70b-instruct` | 4 | 1200s | 大对象长稳态 |

重点比较:

| 指标 | 看什么 |
|---|---|
| Read Device P95/P99 | object 级读尾延迟是否恶化 |
| Write Device P95/P99 | 写尾是否爆炸 |
| `iostat r_await/w_await` | 设备层平均等待时间 |
| first 5min vs last 5min | 长时间运行是否 drift |
| `%util` | 是否设备层接近饱和 |

## 4. 一键脚本

脚本路径:

```bash
scripts/dgx_spark_kvcache_sweep.sh
```

挂载点通过 `DISK_TARGETS` 传入，格式是:

```bash
DISK_TARGETS="label1=/mnt/disk1,label2=/mnt/disk2"
```

### 4.1 Realistic 主测试

```bash
cd /home/ficus/llm/storage
source .venv/bin/activate

DISK_TARGETS="biwin=/mnt/biwin,seagate=/mnt/seagate,zhitai=/mnt/zhitai,wd=/mnt/wd" \
SUITE=realistic \
GPU_MEM_GB=32 \
CPU_MEM_GB=32 \
NUM_GPUS=1 \
TENSOR_PARALLEL=1 \
bash scripts/dgx_spark_kvcache_sweep.sh
```

如果确认 DGX Spark 有 VRAM 128GB + DRAM 128GB 两层资源，可加跑一档:

```bash
DISK_TARGETS="biwin=/mnt/biwin,seagate=/mnt/seagate,zhitai=/mnt/zhitai,wd=/mnt/wd" \
SUITE=realistic \
GPU_MEM_GB=64 \
CPU_MEM_GB=64 \
NUM_GPUS=1 \
TENSOR_PARALLEL=1 \
RESULTS_ROOT=/home/ficus/llm/storage/results/dgx_spark_kvcache/mem64_$(date +%Y%m%d_%H%M%S) \
bash scripts/dgx_spark_kvcache_sweep.sh
```

### 4.2 Pure SSD 排序测试

```bash
DISK_TARGETS="biwin=/mnt/biwin,seagate=/mnt/seagate,zhitai=/mnt/zhitai,wd=/mnt/wd" \
SUITE=pure \
NUM_GPUS=1 \
TENSOR_PARALLEL=1 \
bash scripts/dgx_spark_kvcache_sweep.sh
```

### 4.3 Long steady-state 测试

```bash
DISK_TARGETS="biwin=/mnt/biwin,seagate=/mnt/seagate,zhitai=/mnt/zhitai,wd=/mnt/wd" \
SUITE=long \
GPU_MEM_GB=32 \
CPU_MEM_GB=32 \
NUM_GPUS=1 \
TENSOR_PARALLEL=1 \
bash scripts/dgx_spark_kvcache_sweep.sh
```

### 4.4 全部测试

时间较长，只建议无人值守运行:

```bash
DISK_TARGETS="biwin=/mnt/biwin,seagate=/mnt/seagate,zhitai=/mnt/zhitai,wd=/mnt/wd" \
SUITE=all \
GPU_MEM_GB=32 \
CPU_MEM_GB=32 \
NUM_GPUS=1 \
TENSOR_PARALLEL=1 \
bash scripts/dgx_spark_kvcache_sweep.sh
```

### 4.5 可选 bpftrace

如果只想给少数关键 run 生成 block layer latency / fio 蒸馏信息，可以打开:

```bash
ENABLE_LATENCY_TRACING=1
```

示例:

```bash
DISK_TARGETS="seagate=/mnt/seagate" \
SUITE=realistic \
GPU_MEM_GB=32 \
CPU_MEM_GB=32 \
ENABLE_LATENCY_TRACING=1 \
bash scripts/dgx_spark_kvcache_sweep.sh
```

不建议全矩阵都开 bpftrace。它会增加运行成本，也可能干扰压力测试。

## 5. 单盘手工命令

如果不使用脚本，下面是单盘 70B realistic 主测试命令:

```bash
cd /home/ficus/llm/storage/kv_cache_benchmark
source ../.venv/bin/activate

python3 kv-cache.py \
  --config config.yaml \
  --model llama3.1-70b-instruct \
  --num-users 4 \
  --duration 600 \
  --gpu-mem-gb 32 \
  --cpu-mem-gb 32 \
  --num-gpus 1 \
  --tensor-parallel 1 \
  --generation-mode none \
  --use-burst-trace \
  --burst-trace-path /home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv \
  --trace-speedup 10 \
  --replay-cycles 1 \
  --storage-capacity-gb 200 \
  --cache-dir /mnt/seagate/kvcache_dgx_spark_70b_u4 \
  --seed 42 \
  --output /home/ficus/llm/storage/results/dgx_spark/seagate_70b_u4_600s.json \
  --xlsx-output /home/ficus/llm/storage/results/dgx_spark/seagate_70b_u4_600s.xlsx
```

配套采集设备层时间序列:

```bash
iostat -dx -m 1 > /home/ficus/llm/storage/results/dgx_spark/seagate_70b_u4_iostat.txt 2>&1 &
IOSTAT_PID=$!

# run kv-cache.py here

kill "$IOSTAT_PID"
```

pure SSD 单盘命令:

```bash
python3 kv-cache.py \
  --config config.yaml \
  --model llama3.1-70b-instruct \
  --num-users 4 \
  --duration 300 \
  --gpu-mem-gb 0 \
  --cpu-mem-gb 0 \
  --num-gpus 1 \
  --tensor-parallel 1 \
  --max-concurrent-allocs 2 \
  --generation-mode none \
  --use-burst-trace \
  --burst-trace-path /home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv \
  --trace-speedup 1000 \
  --replay-cycles 0 \
  --storage-capacity-gb 200 \
  --cache-dir /mnt/seagate/kvcache_pure_70b_u4 \
  --seed 42 \
  --output /home/ficus/llm/storage/results/dgx_spark/seagate_pure_70b_u4_300s.json
```

## 6. fio 补充测试

fio 只用于解释设备层瓶颈，不作为 DGX Spark KV cache 主结论。

如果使用已有蒸馏 workload:

```bash
bash scripts/run_fio_sweep.sh
bash scripts/run_fio_sweep_preconditioned.sh
```

如果从 DGX Spark run 的 bpftrace 结果生成了新的 fio `.ini`，建议按这些 qd 扫:

```bash
for qd in 16 32 64 128 256; do
  run_dir="/home/ficus/llm/storage/results/dgx_spark/fio_${qd}"
  mkdir -p "$run_dir"
  cp /path/to/distilled_kvcache.ini "$run_dir/fio.ini"
  {
    echo "filename=/mnt/seagate/fio_dgx_spark_kvcache.dat"
    echo "size=100G"
    echo "runtime=120"
    echo "iodepth=$qd"
    echo "iodepth_batch_submit=$qd"
  } >> "$run_dir/fio.ini"
  fio "$run_dir/fio.ini" --output-format=json > "$run_dir/fio_output.json"
done
```

推荐 fio 判读:

| 指标 | 判读 |
|---|---|
| qd=16/32 P99 | 更接近 serving 中可接受队列深度 |
| qd>=128 P99 | 用于看尾延迟崩溃点 |
| read/write P99.9 | 判断写尾和 GC 风险 |
| direct=1 | 绕过 page cache，看真实 SSD |

不要直接用蒸馏出的超大 `iodepth=524288/1048576` 做产品结论。那通常代表系统侧堆积，不是合理裸盘队列深度。

## 7. 结果目录

脚本默认输出:

```text
results/dgx_spark_kvcache/<timestamp>/
├── run_config.txt
├── <disk_label>/
│   ├── realistic_70b_u1_600s/
│   │   ├── kv_cache_summary.json
│   │   ├── kv_cache_summary.xlsx
│   │   ├── kv_cache.log
│   │   ├── iostat.txt
│   │   └── metadata.json
│   ├── realistic_70b_u2_600s/
│   ├── realistic_70b_u4_600s/
│   ├── realistic_70b_u8_600s/
│   ├── realistic_8b_u8_600s/
│   ├── realistic_8b_u16_600s/
│   └── realistic_8b_u32_600s/
```

## 8. 汇总表建议

每个 run 至少汇总这些字段:

| 字段 | 来源 |
|---|---|
| disk label | `metadata.json` |
| model/users/duration | `metadata.json` |
| cache hit rate | `kv_cache_summary.json` |
| requests/sec | `kv_cache_summary.json` |
| read device P95/P99 | `kv_cache_summary.json` |
| write device P95/P99 | `kv_cache_summary.json` |
| E2E P95/P99 | `kv_cache_summary.json` |
| total read/write GB | `kv_cache_summary.json` |
| iostat r_await/w_await avg/P95 | `iostat.txt` |
| first 5min vs last 5min drift | `iostat.txt` |

最终表建议分三张:

1. realistic tiering 表: 作为主结论。
2. long steady-state 表: 作为稳定性结论。
3. pure SSD/fio 表: 作为硬件解释。

## 9. 结论口径

推荐最终报告这样组织:

1. DGX Spark 真实配置下，哪个盘在 70B users=4/8、8B users=16/32 开始出现 object tail latency。
2. 哪个盘在 20-30min 后出现明显 `w_await`、write P99 或 E2E P95 drift。
3. pure SSD 测试是否支持主测试中观察到的盘间差异。
4. fio 是否说明问题来自 128KiB mixed R/W、写尾、GC，还是系统侧排队。

不要把 pure SSD 的失败直接写成 DGX Spark 真实服务失败；它是压力放大测试。DGX Spark 主结论必须以 realistic tiering 和 long steady-state 为准。

