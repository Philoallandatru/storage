# KV Cache Benchmark 配置参数完整参考

本文档汇总 `kv_cache_benchmark/kv-cache.py` 所有命令行参数、按用途分组、并对每个参数说明其作用、默认值和对最终结果的影响。

参考来源：
- `kv_cache_benchmark/kv_cache/cli.py` — argparse 定义
- `kv_cache_benchmark/kv_cache/benchmark.py` — 运行时行为
- `kv_cache_benchmark/kv_cache/cache.py` — 三层存储
- `kv_cache_benchmark/kv_cache/models.py` — 模型规格
- `scripts/cross_vendor_kv_cache.sh` — K1-K5 实际配置

---

## 1. 用法概览

```bash
python3 kv-cache.py \
    --config kv_cache_benchmark/config.yaml \
    --model llama3.1-70b-instruct \
    --num-users 4 \
    --duration 180 \
    --gpu-mem-gb 0 \
    --cpu-mem-gb 0 \
    --num-gpus 8 \
    --tensor-parallel 8 \
    --max-concurrent-allocs 2 \
    --generation-mode none \
    --use-burst-trace \
    --burst-trace-path /home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv \
    --trace-speedup 1000 \
    --cache-dir /mnt/nvme/cache \
    --seed 42 \
    --output result.json
```

---

## 2. 模型与并发

| 参数 | 类型 | 默认 | 含义 |
|------|------|------|------|
| `--model` | str | (必填) | 模型名，从 `config.yaml` 的 `models:` 段读取。常用：`llama3.1-8b`, `llama3.1-70b-instruct`, `llama3.1-405b-instruct` |
| `--num-users` | int | 1 | 并发用户数。每个用户独立发起请求、跑多轮对话 |
| `--num-gpus` | int | 1 | 模拟 GPU 总数 = `num_gpus × gpu_mem_gb`。例如 `--num-gpus 8 --gpu-mem-gb 141` 模拟 8×H200 |
| `--tensor-parallel` | int | 1 | TP 度，每个 GPU 存 1/TP 的 KV cache 条目。`llama3.1-70b-instruct` 通常 TP=8 |
| `--request-rate` | float | 0 | 目标请求到达率 (req/s)。0 = 无限制，按 trace 时间戳 |
| `--max-concurrent-allocs` | int | 0 | 同时分配 KV cache 的最大并发数。**0 = 不限**。原版 K1-K5 设 2，限制压力 |
| `--max-requests` | int | 0 | 跑完 N 个请求后停止。0 = 用 `--duration` 计时 |

---

## 3. 三层存储容量配置

KV cache 模拟真实 LLM serving 的"瀑布"模型：GPU VRAM → CPU DRAM → NVMe。

```
Tier-1 (GPU VRAM)  →  Tier-2 (CPU DRAM)  →  Tier-3 (NVMe)
   很快                      慢                      最慢
   满了往 Tier-2 evict       满了往 Tier-3 evict
```

| 参数 | 默认 | 含义 |
|------|------|------|
| `--gpu-mem-gb` | 0 | 每个 GPU 的 VRAM 大小（GiB）。**Tier-1 总容量 = num_gpus × gpu_mem_gb** |
| `--cpu-mem-gb` | 0 | Tier-2 (DRAM) 总容量（GiB） |
| `--storage-capacity-gb` | 0 | Tier-3 (NVMe) 容量（GiB）。0 = 自动检测 `--cache-dir` 的剩余空间 |

### 容量配置影响

- **`--gpu-mem-gb 0 --cpu-mem-gb 0`** = **纯 NVMe tier**，所有 KV cache 都打到磁盘
  - 最能体现存储性能差异
  - 6-9 号 K1-K5 用的就是这个
- **`--gpu-mem-gb 141 --cpu-mem-gb 141`** = 真实 8×H200 部署，命中率 96%+
- 三层全 0 = 无存储容量，跑几个请求就报错

---

## 4. 路径与输出

| 参数 | 含义 |
|------|------|
| `--config` | YAML 配置文件路径。默认是 `kv_cache_benchmark/config.yaml`，里面有模型规格、ShareGPT 设置、autoscaler 阈值 |
| `--cache-dir` | Tier-3 NVMe 缓存目录。所有溢出的 KV cache 序列化为 `.npy` 文件存在这里 |
| `--output` | benchmark 结果 JSON 路径（含 summary、throughput_timeline、latencies） |
| `--xlsx-output` | 可选，Excel 格式的结果 |
| `--log-level` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`。原版 K1-K5 用 WARNING 减少日志噪音 |

---

## 5. 工作负载生成（关键！）

KV cache 测试有 3 种负载来源：

### 5.1 BurstGPT trace（默认，最常用）

| 参数 | 默认 | 含义 |
|------|------|------|
| `--use-burst-trace` | flag | 启用 Azure BurstGPT 真实 trace |
| `--burst-trace-path` | (需要时必填) | trace CSV 路径 |
| `--trace-speedup` | 1 | 时间戳压缩倍数。**`1000` 是 6-9 号标准配置**——把 33 小时 trace 压成 ~2 min |
| `--replay-cycles` | 0 | trace 重播次数。0 = 无限循环直到 duration 结束 |
| `--validation-trace` | (可选) | 第二个 trace 用于交叉验证 |

### 5.2 ShareGPT 数据集

| 参数 | 含义 |
|------|------|
| `--dataset-path` | ShareGPT JSON 文件路径（如 `ShareGPT_V3_unfiltered_cleaned_split_no_imsorry.json`） |
| `--max-conversations` | 最多用多少条 ShareGPT 对话 |

### 5.3 合成负载

| 参数 | 含义 |
|------|------|
| `--enable-autoscaling` | 启用自动扩缩（QoS 或 capacity 模式） |
| `--autoscaler-mode` | `qos` = 维持 SLA 不超载；`capacity` = 最大化吞吐 |
| `--target-saturation` | 目标饱和度（0.0-1.0），QoS 模式用 |
| `--max-conversations` | ShareGPT 模式下限制总对话数 |

---

## 6. 模型行为

| 参数 | 默认 | 含义 |
|------|------|------|
| `--generation-mode` | `fast` | `none` / `fast` / `realistic`。**`none` 不模拟 decode 时间**（只看存储），`fast` 加 token 间小延迟，`realistic` 模拟真实 LLM 速度 |
| `--enable-prefix-caching` | True | 系统提示词 + 公共短语的 prefix cache |
| `--disable-prefix-caching` | flag | 禁用 prefix cache（更严苛的测试） |
| `--disable-multi-turn` | flag | 禁用多轮对话（每轮独立 KV cache） |
| `--enable-rag` | flag | 加 RAG 文档加载 |
| `--rag-num-docs` | 0 | RAG 文档数 |
| `--seed` | 42 | 随机种子。所有 K1-K5 用同一个 seed 保证可复现 |

---

## 7. 性能分析模式

| 参数 | 含义 |
|------|------|
| `--performance-profile` | `latency` / `throughput`。决定 pass/fail 阈值 |
| `--io-trace-log` | 路径。开启后 KV cache 操作记成 CSV（trace mode，**不做真实 I/O**）|
| `--enable-latency-tracing` | 启用 bpftrace 设备级延迟直方图。**需要 sudo + bpftrace** |

### Trace mode vs 真实 I/O mode

```
默认 (无 --io-trace-log):  → 真实 NVMe I/O  → iostat 看到真实压力
+ --io-trace-log FILE    → NullBackend    → bpftrace 看不到真实 I/O
```

跑分对照实验常用两轮：trace mode 抓 bpftrace，hw mode 抓 iostat。

---

## 8. SSD 预条件（可选）

| 参数 | 默认 | 含义 |
|------|------|------|
| `--precondition` | flag | 跑测试前先填满 SSD 让结果稳定 |
| `--precondition-size-gb` | 0 | 预条件数据量。0 = 2× NVMe 容量 |
| `--precondition-threads` | 0 | 并行写线程数。0 = `os.cpu_count()` |

---

## 9. 6-9 号 K1-K5 标准配置（来自 `cross_vendor_kv_cache.sh`）

```bash
python3 kv-cache.py \
  --config config.yaml \
  --model <llama3.1-8b or llama3.1-70b-instruct> \
  --num-users <1/4/8/16/4> \
  --duration <120/120/120/120/180> \
  --gpu-mem-gb 0 \        # ← 关键：纯 NVMe tier
  --cpu-mem-gb 0 \        # ← 关键：DRAM 也关闭
  --num-gpus 8 \
  --tensor-parallel 8 \
  --max-concurrent-allocs 2 \
  --generation-mode none \  # ← 关键：不算 decode
  --use-burst-trace \
  --burst-trace-path /home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv \
  --trace-speedup 1000 \    # ← 关键：压缩 1000×
  --replay-cycles 0 \
  --cache-dir <per-disk mount> \
  --seed 42 \
  --output kv_cache_summary.json \
  --log-level WARNING
```

| Scenario | Model | Users | Duration |
|----------|-------|-------|----------|
| **K1** | llama3.1-8b | 1 | 120s |
| **K2** | llama3.1-8b | 4 | 120s |
| **K3** | llama3.1-8b | 8 | 120s |
| **K4** | llama3.1-8b | **16** | 120s |
| **K5** | llama3.1-70b-instruct | **4** | **180s** |

### K4 与 K5 的差异

| 维度 | K4 | K5 |
|------|----|----|
| 模型 | 8B（小模型） | 70B（大模型） |
| 用户数 | 16（高并发） | 4（中并发） |
| 时长 | 120s | 180s |
| 工作集 | 每请求 ~20 KB KV | 每请求 ~140 KB KV |
| 写入压力 | 高（每 user 短间隔） | 低但每条大 |
| **触发场景** | KV cache 频繁 evict，cache miss 主导 | cache hit 高，但每次 miss 写盘量大 |
| **存储场景** | 读多写少，高 IOPS | 写带宽压力大 |

---

## 10. K4 vs K5 GC drift 测试配置（2026-06-09 与 06-29 重跑）

```bash
# K4 GC drift（8B × 16u × 30min）
python3 kv-cache.py --config config.yaml \
  --model llama3.1-8b \
  --num-users 16 \
  --duration 1800 \
  --gpu-mem-gb 0 --cpu-mem-gb 0 \
  --num-gpus 8 --tensor-parallel 8 \
  --max-concurrent-allocs 2 \
  --generation-mode none \
  --use-burst-trace \
  --burst-trace-path /home/ficus/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv \
  --trace-speedup 1000 \
  --replay-cycles 0 \
  --cache-dir /mnt/<ssd>/kvcache_k4_gc/cache \
  --seed 42 \
  --enable-autoscaling \        # ← 用于记录 timeline
  --enable-latency-tracing \    # ← 需要 sudo
  --output k4_result.json \
  --log-level INFO

# K5 GC drift（70B × 6u × 30min，2026-06-09 用的 6u 而非标准 4u）
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
  --cache-dir /mnt/<ssd>/kvcache_k5_gc/cache \
  --seed 42 \
  --enable-autoscaling \
  --enable-latency-tracing \
  --output k5_result.json
```

差异：
- `num_users` 从 K5 标准 4 改为 **6**（6-9 当时的选择）
- `duration` 从 180s 拉到 **1800s**（30min GC drift 测试）
- 加上 `--enable-autoscaling` 让 throughput_timeline 自动记录

---

## 11. 常见陷阱

### ⚠️ `--gpu-mem-gb 0 --cpu-mem-gb 0` 不是默认

这两个参数默认是 **0**，但默认行为是"使用模型规格里的隐含值"。如果只跑 `--cache-dir /tmp/`，不会自动让所有 KV cache 都落到磁盘。**必须显式写 `--gpu-mem-gb 0 --cpu-mem-gb 0`** 才是纯 NVMe 测试。

### ⚠️ `--max-concurrent-allocs 2` 不是默认值

默认是 0（不限），设 2 是有意压低并发，让存储 I/O 成为瓶颈。如果设 0，autoscaler 会快速堆用户到 32+，掩盖存储性能。

### ⚠️ `trace-speedup 1000` 会让真实时间失真

trace 时间戳被压缩 1000 倍，所以吞吐量也是相对的。**不要拿绝对值跟真实 LLM serving 比较**。

### ⚠️ `--enable-autoscaling` 是 timeline 记录的前提

不带这个参数，benchmark 跑完 throughput_timeline 是空数组。如果想画 token/s 时序图，**必须加 `--enable-autoscaling`**。

### ⚠️ `--enable-latency-tracing` 需要 sudo + bpftrace

agent 经常 sudo 缓存过期，跑这个会失败。可以省略，timeline 仍然能记录。

---

## 12. 输出 JSON 结构

```json
{
  "requests_completed": 29260,
  "total_tokens_generated": 3213354,
  "total_storage_io_latency": 1234.5,
  "total_generation_latency": 0.0,
  "end_to_end_latencies": [7.0, 8.9, ...],
  "storage_latencies": [...],
  "prefill_latencies": [...],
  "decode_latencies": [...],
  "throughput_timeline": [
    {"timestamp": 10, "throughput_tokens_per_sec": 1870.8},
    {"timestamp": 20, "throughput_tokens_per_sec": 1337.1},
    ...
  ],
  "summary": {
    "total_requests": 29260,
    "total_tokens": 3213354,
    "elapsed_time": 1800.1,
    "avg_throughput_tokens_per_sec": 1785.1,
    "storage_throughput_tokens_per_sec": 400.1,
    "cache_stats": {
      "cache_hit_rate": 0.963,
      "read_bytes": 4642000000000,
      "write_bytes": 559000000000,
      "read_iops": 149367,
      "write_iops": 29260
    },
    "autoscaling_summary": {
      "initial_users": 6,
      "final_users": 1,
      "total_scale_events": 40
    }
  }
}
```

关键字段：
- `throughput_timeline[]` — 每 1s（默认）记录一次累计 token/s 快照，画时序图用
- `cache_stats` — R/W 比例、IOPS、命中率
- `autoscaling_summary` — autoscaler 跑过的初始/最终用户数、扩缩事件次数
- `autoscaling_stats[]` — 每次扩缩的细节（时间戳、目标用户数、当时的 latency 和 throughput）

---

## 13. 重新跑 6-9 号 K4/K5 标准版（最简）

```bash
# 在每块盘上跑一次（来自 scripts/cross_vendor_kv_cache.sh）
bash scripts/cross_vendor_kv_cache.sh K4   # 4 盘串行 K4
bash scripts/cross_vendor_kv_cache.sh K5   # 4 盘串行 K5

# 只跑一块盘
bash scripts/cross_vendor_kv_cache_k4_only.sh   # K4 across all 4 disks
bash scripts/cross_vendor_kv_cache_k5_only.sh   # K5 across all 4 disks
```

完整 5 场景 × 4 盘 串行总耗时 ~45 分钟。