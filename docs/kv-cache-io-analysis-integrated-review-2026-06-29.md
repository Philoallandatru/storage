# KV Cache I/O 模式整合审查

**日期:** 2026-06-29  
**范围:** synthetic / ShareGPT / BurstGPT 的 KV cache I/O 模式对比  
**核心证据:** `tracepoint:block:block_rq_issue` per-I/O block trace  
**辅助证据:** `bpftrace` latency stack、`iostat`、应用层 KV trace、fio sweep  
**三路图表:** `docs/assets/io-three-way-comparison/`  
**ShareGPT vs BurstGPT 细图:** `docs/assets/sharegpt-vs-burstgpt/`

## 一句话结论

KV cache 到 NVMe 的真实 I/O 不能再简单写成“随机大块 I/O”。更准确的结论是：

- **Decode read:** 真实 block 层是高随机、大跨度 LBA 跳跃，是 SSD 选型的主要压力源。
- **Prefill / eviction write:** 大多接近连续追加写，和 decode read 是两种不同模式。
- **Synthetic fio:** 适合做可重复、可控压力，但没有真实请求节奏和相邻 LBA 语义。
- **ShareGPT:** 更接近真实聊天，压力较轻，读路径有较多连续/近邻成分。
- **BurstGPT:** 压力更强，更接近随机读压力基线，是更好的 SSD stress workload。

这份文档同时审查了旧报告的问题：模拟 LBA、`iostat %rrqm=0`、bpftrace heatmap 都不能单独支持“真实 LBA 随机性”结论。真实 LBA 结论必须来自每条 block request 的 `sector` 字段。

## 结论边界

可以保留的结论：

- KV cache offload 的设备层 request size 主要集中在 **128 KiB**。
- 混合 workload 中，读占主导；在强制 NVMe 配置下，ShareGPT/BurstGPT 都是 read-heavy。
- BurstGPT 比 ShareGPT 更重、更随机：更高 IOPS/BW、更高 read LBA 大跳比例。
- 写路径与读路径不同，写更连续，读更随机。

必须修正或降级的旧结论：

- “KV cache 是 100% 随机大块 I/O”过粗，需要拆成 read/write 和 phase。
- 应用层 Key 模拟 LBA 不能当作真实 SSD LBA。
- `iostat %rrqm≈0` 只能说明块层没有合并，不能说明 LBA 跳跃分布。
- bpftrace `@d[dev,sector]` 是 in-flight/D2C 辅助 map，不应再拿来算完整 sequential ratio。

## 证据类型审查

| 数据源 | 代表文件 | 能证明什么 | 不能证明什么 | 当前处理 |
|---|---|---|---|---|
| 应用层 KV trace | `io_trace_sharegpt_*.csv.zst` | Key、tier、phase、应用层 locality | 真实 SSD LBA | 只用于应用层行为解释 |
| `iostat` | `iostat_*.txt/log` | 每秒 IOPS、BW、await、util、merge | per-request LBA | 只作设备聚合背景 |
| bpftrace latency stack | `storage_latency_stack.bt` 输出 | Q2D/D2C、block size、latency、LBA heatmap | 完整逐 I/O LBA 序列 | 用于 latency/size/热区，不用于 sequential ratio |
| per-I/O block trace | `block_lba_trace.csv` | 每条 block I/O 的时间、sector、size、rwbs | 应用 Key/请求 ID | 作为真实 LBA 结论主证据 |
| fio synthetic | `fio_sweep/*.json` | 可重复压力、QD/latency 曲线 | 真实请求时序和相邻 LBA | 作为压力上限/设备对比 |

关键原则：**空间随机性必须看真实 `sector` 序列，不能由 Key offset、iostat merge、或 bpftrace histogram 反推。**

## bpftrace 方法和原理

### bpftrace 是什么

`bpftrace` 是基于 Linux eBPF 的动态 tracing 工具。它可以挂到内核 tracepoint、kprobe、uretprobe 等事件上，在不修改应用程序的情况下采集内核路径上的指标。

在本项目里，它主要用于两类采集：

1. **统计型 bpftrace:** 用 hist/map 聚合 Q2D、D2C、block size、queue depth、LBA heatmap。
2. **逐 I/O bpftrace:** 每次 `block_rq_issue` 打印一行 CSV，用于真实 LBA 序列分析。

### Linux block I/O 的关键事件

一次 block I/O 简化后经过：

```text
block_rq_insert  ->  block_rq_issue  ->  block_rq_complete
进入队列             下发到驱动/设备       设备完成
```

对应指标：

| 阶段 | 含义 |
|---|---|
| Q2D | Queue-to-Dispatch，进入 block queue 到下发设备的等待时间 |
| D2C | Dispatch-to-Complete，设备处理到完成的时间 |
| `args->sector` | I/O 起始 sector，512-byte sector 单位 |
| `args->bytes` | 该 block request 的字节数 |
| `args->rwbs` | read/write/metadata/sync/readahead 等标记 |

真实 LBA 计算：

```text
LBA byte offset = sector * 512
```

### `storage_latency_stack.bt`

脚本位置：

```text
kv_cache_benchmark/utils/storage_latency_stack.bt
```

它同时采集：

- `@q2d_read_us` / `@q2d_write_us`
- `@d2c_read_us` / `@d2c_write_us`
- `@bssplit_read_kb` / `@bssplit_write_kb`
- `@qd_read` / `@qd_write`
- `@lba_read_gb` / `@lba_write_gb`
- VFS read/write latency
- fsync latency

它适合回答：

- 设备是不是瓶颈。
- read/write latency 的尾部在哪里。
- block request size 大概分布如何。
- I/O 落在设备哪个大致空间区间。

它不适合直接回答：

- 相邻两次 read 之间到底跳了多少 MiB。
- sequential ratio 精确是多少。

原因是它输出的大多是 histogram/map 聚合，不是完整事件流。特别是 `@d[dev,sector]` 是 D2C 计时用的临时 map，代表仍在跟踪或最后残留的请求，不是完整 LBA 历史。

### `trace_block_lba.bt`

脚本位置：

```text
scripts/trace_block_lba.bt
```

核心逻辑：

```bpftrace
tracepoint:block:block_rq_issue
/args->dev == $1/
{
  printf("%llu,%u,%llu,%u,%s,%s,%d\n",
         nsecs,
         args->dev,
         args->sector,
         args->bytes,
         args->rwbs,
         comm,
         pid);
}
```

输出 schema：

```text
timestamp_ns,dev,sector,bytes,rwbs,comm,pid
```

这个脚本只做一件事：把目标 block device 上每次 `block_rq_issue` 作为 CSV 打出来。它牺牲了一些低开销聚合能力，但换来完整 per-I/O 序列。

### 为什么要追 parent device

最初按 partition dev_t 过滤时只捕获到 header，真实 I/O 发生在 parent block device 上。因此有效 ShareGPT/BurstGPT trace 使用：

```text
device=/dev/nvme0n1
filesystem=/dev/nvme0n1p4 ext4 /
dev_t=271581194
```

这一点很重要。block layer 里 I/O 可能经过 partition/remap 后出现在 parent device。如果过滤错 dev_t，会得到空 trace。

### dev_t 怎么算

Linux block dev_t 可按 `(major << 20) | minor` 计算。

例子：

```bash
lsblk -no MAJ:MIN /dev/nvme0n1
uv run python - <<'PY'
major, minor = 259, 10
print((major << 20) | minor)
PY
```

运行：

```bash
sudo bpftrace scripts/trace_block_lba.bt 271581194 > block_lba_trace.csv
```

## per-I/O LBA 分析方法

解析脚本：

```text
scripts/analyze_block_lba_trace.py
```

核心计算：

```text
start = sector * 512
end = start + bytes
delta = current.start - previous.end
abs_delta_mib = abs(delta) / 1024 / 1024
```

按 read 和 write 分开统计：

| 指标 | 含义 |
|---|---|
| `exact_contiguous_pct` | 当前 I/O 正好接在上一条 I/O 后面 |
| `near_1mib_pct` | 相邻 I/O 距离小于 1 MiB |
| `jump_ge_100mib_pct` | 相邻 I/O 距离大于等于 100 MiB |
| `abs_delta_mib.p50/p95/p99` | 相邻跳跃距离分布 |
| `direction_run_length` | 连续同方向前进/后退的 run 长度 |

为什么 `delta = current.start - previous.end` 而不是 `current.start - previous.start`：

- 如果当前 I/O 正好接在上一条末尾，`delta = 0`，表示连续。
- 如果两条 I/O 重叠或访问同一区域，delta 可能为负。
- 这样更符合 block sequentiality 的定义。

## 真实读写分裂结论

参考文档：

```text
docs/kv-cache-nvme-offload-real-io-analysis-2026-06-29.md
```

该文档使用真实 block trace：

```text
results/kvcache-profile/per_io_lba_ext4_rw_20260629_032924/block_lba_trace.csv
```

摘要：

| 指标 | Read | Write |
|---|---:|---:|
| Adjacent pairs | 2,068,811 | 418,497 |
| Exact contiguous | 2.5% | 75.1% |
| Near `<1 MiB` | 3.4% | 81.6% |
| Jump `>=100 MiB` | 95.1% | 17.2% |
| Delta p50 | 56,997 MiB | 0 MiB |
| Delta p95 | 181,721 MiB | 12,964 MiB |

解释：

- Decode read 是大跨度随机读，p50 跳跃已经达到 56 GiB 级别。
- Prefill write 更接近连续追加写，75% 精确连续。
- 读写不能混成一个 I/O 模式，否则会掩盖真正压力源。

## Synthetic / ShareGPT / BurstGPT 三路对比

三路对比图来自：

```text
docs/assets/io-three-way-comparison/
```

数据源：

| Workload | 数据源 | 性质 |
|---|---|---|
| Synthetic | `results/kvcache-profile/fio_sweep/sharegpt_8b_cpuhalf_qd32/fio_output.json` | fio 蒸馏/合成压力 |
| ShareGPT | `results/kvcache-profile/sharegpt_kvcache_20260629_140729/block_lba_trace.csv` | 真实聊天回放，强制 NVMe |
| BurstGPT | `results/kvcache-profile/burstgpt_kvcache_20260629_141010/block_lba_trace.csv` | 生产 trace speedup=1000，强制 NVMe |

![dashboard](assets/io-three-way-comparison/01_signal_dashboard.png)

| 指标 | Synthetic QD32 | ShareGPT | BurstGPT |
|---|---:|---:|---:|
| IOPS | 30,545 | 14,063 | 35,195 |
| BW | 2.85 GiB/s | 1.64 GiB/s | 4.25 GiB/s |
| Read event % | 61% | 93.86% | 92.03% |
| Read exact-contiguous | n/a | 41.77% | 10.08% |
| Read `>=100 MiB` jump | n/a | 56.97% | 89.11% |
| Write exact-contiguous | n/a | 94.37% | 97.63% |
| Dominant block size | fio bssplit | 128 KiB, 93.94% | 128 KiB, 98.52% |
| LBA span | n/a | 389.35 GiB | 389.35 GiB |

Synthetic 没有 per-I/O LBA adjacency 概念。fio 可以配置随机读写和 bssplit，但它不保留真实请求间的 Key reuse、session、arrival pattern，所以不能和 ShareGPT/BurstGPT 的 LBA delta 直接同列比较。

## ShareGPT vs BurstGPT 真实 block trace

详细文档：

```text
docs/kv-cache-sharegpt-vs-burstgpt-io-2026-06-29.md
```

![timeline](assets/sharegpt-vs-burstgpt/01_timeline_iops_bandwidth.png)

Benchmark 层：

| Metric | ShareGPT | BurstGPT |
|---|---:|---:|
| Requests completed | 1,238 | 564 |
| Tokens | 329,019 | 140,232 |
| Benchmark elapsed | 122.58s | 120.00s |
| KV storage read | 215.34 GiB | 506.71 GiB |
| KV storage write | 11.78 GiB | 41.31 GiB |
| KV read BW | 1.76 GiB/s | 4.22 GiB/s |
| KV write BW | 0.10 GiB/s | 0.34 GiB/s |

Block trace 层：

| Metric | ShareGPT | BurstGPT |
|---|---:|---:|
| Block events | 1,981,685 | 4,566,627 |
| Trace duration | 140.91s | 129.75s |
| Read events | 1,860,197 | 4,202,656 |
| Write events | 121,488 | 363,971 |
| Block read bytes | 216.58 GiB | 507.29 GiB |
| Block write bytes | 14.08 GiB | 43.69 GiB |
| IOPS | 14,063 | 35,195 |
| Bandwidth | 1.64 GiB/s | 4.25 GiB/s |
| Dominant request size | 128 KiB | 128 KiB |

![delta](assets/sharegpt-vs-burstgpt/03_lba_delta_signature.png)

LBA signature：

| Metric | ShareGPT read | BurstGPT read | ShareGPT write | BurstGPT write |
|---|---:|---:|---:|---:|
| Exact contiguous | 41.77% | 10.08% | 94.37% | 97.63% |
| Near `<1 MiB` | 42.27% | 10.30% | 96.36% | 98.40% |
| Jump `>=100 MiB` | 56.97% | 89.11% | 3.29% | 1.40% |
| Abs delta p50 | 2,674.75 MiB | 31,055.75 MiB | 0.00 MiB | 0.00 MiB |

解释：

- BurstGPT 读更随机，89.11% 相邻 read 跨越至少 100 MiB。
- ShareGPT 仍有大量随机跳，但保留了 41.77% 连续 read adjacency。
- 两者写路径都高度连续，说明写入不是主要随机压力源。

## 为什么 Synthetic、ShareGPT、BurstGPT 结果不同

### Synthetic

Synthetic fio 是蒸馏后的设备压力模型。它的优势是可重复、可扫 QD、可比较 SSD tail latency。

在 QD32 的 ShareGPT-like fio sweep 中：

| 指标 | 值 |
|---|---:|
| rwmixread | 61% |
| Read IOPS | 18,636 |
| Write IOPS | 11,909 |
| Total IOPS | 30,545 |
| Read BW | 1,644.7 MiB/s |
| Write BW | 1,272.5 MiB/s |
| Total BW | 2.85 GiB/s |
| Read P99 | 6.52 ms |
| Write P99 | 1.24 ms |

它适合回答“设备在这种读写比例和 QD 下表现如何”，不适合回答“真实请求的 LBA 是否连续”。

### ShareGPT

ShareGPT 更像真实聊天 workload。它完成请求更多、token 更多，但 block 层压力低于 BurstGPT。

其特征：

- IOPS 和 BW 明显低于 BurstGPT。
- read-heavy，但读 LBA 有较多连续/近邻成分。
- 适合作为“真实聊天 replay”和功能验证。
- 不适合作为唯一 SSD stress baseline。

### BurstGPT

BurstGPT 是生产 API trace。这里使用 `trace_speedup=1000`，并强制 `gpu_mem=0`、`cpu_mem=0`，把 KV I/O 推到 NVMe。

其特征：

- IOPS 最高，35.2K。
- BW 最高，4.25 GiB/s。
- read LBA 大跳比例最高，89.11%。
- 更适合作为 SSD 随机读压力基线。

## fio sweep 和 QD 的解读

fio sweep 结果显示，workload 对 QD 的敏感度不同。

| Workload | rwmixread | QD32 R P99 | QD1024 R P99 | Max R IOPS |
|---|---:|---:|---:|---:|
| ShareGPT-like | 61% | 6.52 ms | 166.72 ms | 18,636 |
| BurstGPT-like | 91% | 3.56 ms | 68.68 ms | 21,065 |
| Generic TP8 | 73% | 5.08 ms | 156.24 ms | 13,466 |

审查结论：

- QD32 更接近可用产品测试点。
- QD1024 是极限压力，能暴露 tail latency，但不应直接作为常规产品指标。
- bpftrace 蒸馏出的极大 in-flight/QD 信号不应原样拿去做 fio QD 参数。

## 预条件化影响

preconditioning sweep 显示，SSD 状态会显著影响 tail latency。

| Workload | QD | R IOPS Δ | R P99 Δ | W IOPS Δ | W P99 Δ |
|---|---:|---:|---:|---:|---:|
| BurstGPT-like | 32 | +4% | +1% | +4% | -98% |
| BurstGPT-like | 1024 | +4% | -10% | +3% | -29% |
| ShareGPT-like | 32 | +9% | -11% | +9% | +7% |
| ShareGPT-like | 1024 | +15% | -33% | +15% | -42% |

这说明：

- 写 tail latency 对 SSD 内部状态非常敏感。
- 高 QD 下 read tail 也会受 GC/FTL 状态影响。
- 如果要比较 SSD，必须固定 preconditioning 策略。

## 旧文档审查

| 文档 | 审查结果 |
|---|---|
| `docs/kv-cache-io-randomness-2026-06-25.md` | iostat 结论可作为聚合层背景；不能单独证明真实 LBA 随机性 |
| `docs/kv-cache-io-lba-pattern-2026-06-25.md` | 应用层 Key 模拟 LBA 有解释价值；不能当真实 LBA |
| `docs/kv-cache-lba-timeline-analysis-2026-06-25.md` | 若基于模拟 LBA 或不完整 bpftrace map，应降级为探索图 |
| `docs/kv-cache-nvme-offload-real-io-analysis-2026-06-29.md` | 当前真实 LBA 主证据，结论可信度最高 |
| `docs/kv-cache-sharegpt-vs-burstgpt-io-2026-06-29.md` | ShareGPT/BurstGPT 真实 block trace 对比，可保留 |
| `docs/assets/io-three-way-comparison/*` | 已修正 synthetic QD32 IOPS/BW 后可作为综合图使用 |

## 推荐的最终说法

面向 SSD 产品和 KV cache offload 场景，建议使用以下表述：

> KV cache offload 的设备层 I/O 是读写分裂的。Prefill/eviction 写入大多连续或近连续；decode 读取在真实 block LBA 上表现为大跨度随机读。BurstGPT forced-NVMe replay 比 ShareGPT 更能施加随机读压力；ShareGPT 更适合作为真实聊天 replay；synthetic fio 适合做可重复设备边界扫描，但不能替代真实 trace 的 LBA 结论。

## 后续测试建议

1. 对 ShareGPT/BurstGPT 各跑 3 次，报告 median 和方差。
2. 将 per-I/O trace 跑在独立测试盘，而不是 root ext4，减少背景 I/O。
3. 同时采集应用层 Key trace 和 block trace，用时间窗口对齐应用 Key 与真实 LBA。
4. 固定 SSD preconditioning 状态，再做跨盘对比。
5. 保留三件套：`iostat` 看设备聚合，`storage_latency_stack.bt` 看 latency/size，`trace_block_lba.bt` 看真实 LBA。
