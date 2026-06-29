# AI SSD 预研关键测试数据、方向判断与产品设计推理

**日期:** 2026-06-29  
**范围:** KV cache offload、Mooncake SSD offload、本地 fio/synthetic、ShareGPT/BurstGPT、跨 SSD 长稳态测试  
**目标:** 把现有测试资料整理成可用于 AI SSD 预研和产品定义讨论的决策材料

## 0. 结论摘要

现有数据已经足够支持一个阶段性判断：

> AI SSD 的核心机会不是继续堆顺序读写峰值，而是在 LLM KV cache / context memory 场景下，提供 128 KiB 级大块随机读的稳定尾延迟、长稳态 GC 可控性、读优先调度、可观测 telemetry，以及未来 GDS / GPU-centric 数据路径支持。

但现有数据还不能直接支持“某一块盘就是最终生产选型”或“某个本地 Mooncake 百分比等同官方 benchmark”的结论。原因是：部分数据是 forced-NVMe 压力测试，部分是 synthetic fio，Mooncake SSD 复测虽然触发了 SSD path，但仍有 storage warning；跨盘长稳态测试也还没有覆盖 GDS、多盘分片、企业盘、24h soak 和生产 tiering。

因此，本报告采用三层逻辑：

1. **数据事实:** 只列有原始 trace / benchmark / 日志支撑的事实。
2. **工程判断:** 从事实推导 workload 特征和系统瓶颈。
3. **产品方向:** 再把工程判断转成 AI SSD 预研与产品设计方向。

## 1. 证据强度分级

| 证据类型 | 代表资料 | 能证明什么 | 不能证明什么 | 可信度 |
|---|---|---|---|---|
| per-I/O block trace | `block_rq_issue` CSV | 真实 block LBA、request size、读写 split、随机/连续性 | 应用层 key 与请求语义的完整映射 | 最高 |
| KV benchmark summary | `kv-cache.py` 输出 | KV storage read/write、吞吐、请求数、cache 行为 | 真实 LBA 随机性 | 高 |
| Mooncake activation logs | `Storage root directory`、`read store`、`O_DIRECT` | SSD offload path 是否真实触发 | 清洁生产级性能 | 高 |
| fio synthetic sweep | fio JSON | 可重复设备压力、QD/P99 曲线 | 真实请求时序、prefix reuse、LBA adjacency | 中 |
| iostat | 聚合 IOPS/BW/await/util | 设备级活动、长稳态漂移 | per-request LBA、是否来自 SSD offload | 中低 |
| 旧模拟 LBA / bpftrace heatmap | 6 月 25 日旧报告 | 探索性可视化 | 真实 SSD LBA 结论 | 低，已降级 |

关键原则：

> 涉及“真实 LBA 随机性”的结论，只能以 per-I/O block trace 为主证据；iostat、应用层 key offset、bpftrace histogram 只能辅助解释。

## 2. 关键测试数据整理

### 2.1 真实 block LBA：读写路径明显分裂

资料来源：

- `docs/kv-cache-nvme-offload-real-io-analysis-2026-06-29.md`
- `docs/kv-cache-io-analysis-integrated-review-2026-06-29.md`

核心数据：

| 指标 | Read | Write |
|---|---:|---:|
| Exact contiguous | 2.5% | 75.1% |
| Near `<1 MiB` | 3.4% | 81.6% |
| Jump `>=100 MiB` | 95.1% | 17.2% |
| Abs delta p50 | 56,997 MiB | 0 MiB |
| 主导 request size | 128 KiB | 128 KiB |
| LBA span | 389.35 GiB | 389.35 GiB |

工程解释：

1. KV cache offload 不能再笼统写成“随机大块 I/O”。
2. 更准确的模型是：
   - **decode read:** 大跨度随机读，是 SSD 主要压力源。
   - **prefill / eviction write:** 多数接近连续追加写，但会受 GC、FTL、文件系统和容量压力影响。
3. 128 KiB 是当前实测最重要的 block request 粒度，产品测试不应只看传统 4 KiB random。

产品推理：

如果 SSD 只优化顺序读写峰值，不能解决 decode miss 的大跨度随机读尾延迟。AI SSD 的优先指标应从“顺序 14 GB/s”转向：

- 128 KiB random read P99/P999；
- mixed read-heavy workload 下的 read tail；
- GC 期间 read tail 是否被写放大污染；
- 长稳态下的 latency drift。

### 2.2 ShareGPT vs BurstGPT：真实 workload 不是一种压力

资料来源：

- `docs/kv-cache-sharegpt-vs-burstgpt-io-2026-06-29.md`
- `docs/kv-cache-io-analysis-integrated-review-2026-06-29.md`

测试配置摘要：

| 项 | ShareGPT | BurstGPT |
|---|---|---|
| Runner | `kv-cache.py` | `kv-cache.py` |
| 模型 | `llama3.1-8b` | `llama3.1-8b` |
| Users | 8 | 8 |
| Duration flag | 120s | 120s |
| Cache tier | forced NVMe, `gpu_mem=0`, `cpu_mem=0` | forced NVMe, `gpu_mem=0`, `cpu_mem=0` |
| Trace | `block_rq_issue` per-I/O | `block_rq_issue` per-I/O |

核心数据：

| 指标 | ShareGPT | BurstGPT |
|---|---:|---:|
| Requests completed | 1,238 | 564 |
| KV storage read | 215.34 GiB | 506.71 GiB |
| KV storage write | 11.78 GiB | 41.31 GiB |
| Block events | 1,981,685 | 4,566,627 |
| IOPS | 14,063 | 35,195 |
| Bandwidth | 1.64 GiB/s | 4.25 GiB/s |
| Read events | 93.86% | 92.03% |
| Dominant request size | 128 KiB, 93.94% | 128 KiB, 98.52% |
| Read exact-contiguous | 41.77% | 10.08% |
| Read `>=100 MiB` jump | 56.97% | 89.11% |
| Write exact-contiguous | 94.37% | 97.63% |

工程解释：

1. 两者都是 read-heavy，但压力强度不同。
2. BurstGPT 的读更随机、更重：IOPS 是 ShareGPT 的约 2.5 倍，BW 是约 2.6 倍，read 大跳比例达到 89.11%。
3. ShareGPT 更接近聊天 replay，保留更多连续/近邻读，压力较轻但更贴近日常交互。

产品推理：

AI SSD 测试不能只选一个 workload：

| Workload | 产品测试用途 | 不适合回答的问题 |
|---|---|---|
| BurstGPT | 随机读压力基线、decode miss 风暴、SSD tail 能力 | 普通聊天体验的完整代表 |
| ShareGPT | 真实聊天 replay、prefix reuse、混合行为 | 极限 SSD stress |
| synthetic fio | 可重复设备边界扫描、QD/P99 曲线 | 真实 LBA 跳跃和系统收益 |

预研方向上，应至少保留一组 “ShareGPT realistic” 和一组 “BurstGPT stress”。

### 2.3 fio synthetic：可重复压力，不是真实 LBA 行为

资料来源：

- `docs/kv-cache-io-analysis-integrated-review-2026-06-29.md`
- `docs/kvcache-fio-iodepth-sweep-2026-06-08-zh.md`

修正后的 QD32 ShareGPT-like fio 数据：

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

fio iodepth 观察：

| 观察 | 数据 |
|---|---|
| ShareGPT-like 在 QD32 达到较好点 | 18,636 R IOPS |
| QD64 后 ShareGPT-like R IOPS 下降 | 13,108 R IOPS，约 -30% |
| QD1024 tail 明显恶化 | ShareGPT-like R P99 166.72 ms |
| QD32 更接近可用产品测试点 | QD1024 更像极限压力 |

工程解释：

fio 的价值是稳定、可重复、便于扫 QD、P99、preconditioning。但 fio 丢失了真实请求的：

- session / prefix reuse；
- burst arrival；
- app-level cache hit；
- 相邻 LBA 语义；
- prefill/decode phase 边界。

产品推理：

fio 应该作为 AI SSD 的“设备能力标定层”，不能替代 KV benchmark：

1. 先用 fio 找出设备的 128 KiB random read/write 基线、QD 饱和点、tail cliff。
2. 再用 ShareGPT/BurstGPT 验证系统路径是否真的把这些能力转成 TTFT / throughput 收益。
3. 如果 fio 好但 KV benchmark 差，瓶颈可能在文件系统、CPU copy、GDS fallback、cache manager 或调度。
4. 如果 KV benchmark 好但 fio 差，需要检查是否被 DRAM/page cache/tiering 掩盖。

### 2.4 Mooncake SSD offload：路径已触发，但不是 clean production benchmark

资料来源：

- `docs/mooncake-ssd-offload-reproduction-and-io-analysis-2026-06-29.md`

正式 run：

```text
/home/ficus/mooncake_smoke_test/ssd_retest_formal_20260629_074959
```

测试配置：

| 项 | 值 |
|---|---|
| GPU | RTX 5080 16GB 单卡 |
| 模型 | Qwen3-4B-Instruct-2507 |
| Clients | 8 |
| Rounds | 8 |
| Request length | 3072 |
| Output length | 1 |
| Request rate | 8 |
| Max parallel | 2 |
| Mooncake pool | 10GB |
| SSD offload buffer | 2GB |
| Network | TCP localhost |

SSD path 证据：

| 证据 | 值 | 解释 |
|---|---:|---|
| `Storage root directory is:` | 1 | Mooncake client 拿到 SSD root |
| `IsEnableOffloading result: true` | 存在 | offload enable 生效 |
| offload files | 5402 | 有真实落盘文件 |
| offload du | 41 GiB | 写路径有实际数据量 |
| offload read events | 52 | 有 offload read |
| read store events | 52 | 触达 storage read path |
| O_DIRECT events | 1341 | direct I/O 文件打开大量出现 |

性能数据：

| 配置 | Avg TTFT | P90 TTFT | P99 TTFT | Input throughput | Cache hit |
|---|---:|---:|---:|---:|---:|
| +Mooncake | 4.151s | 9.836s | 12.707s | 3981.8 tok/s | 23.84% |
| +Mooncake+SSD | 3.436s | 8.007s | 9.181s | 4469.9 tok/s | 67.76% |

相对提升：

| 对比 | Avg TTFT | Input throughput |
|---|---:|---:|
| `+Mooncake+SSD` vs GPU only | 降低 29.7% | 提升 24.1% |
| `+Mooncake+SSD` vs `+Mooncake` | 降低 17.2% | 提升 12.3% |

异常：

| 事件 | 计数 |
|---|---:|
| `OBJECT_ALREADY_EXISTS` | 3 |
| `insufficient space` | 86 |
| `Write page to storage` | 43 |

工程解释：

1. 这次 run 已经证明 SSD offload path 真实触发。
2. `+Mooncake+SSD` 的 cache hit、TTFT、throughput 优于 `+Mooncake`，趋势有意义。
3. 但 storage warning 说明 offload layer 仍不健康，不能作为最终生产级 benchmark。
4. 本地配置和官方差异很大：官方是 8 x A100、Qwen3-8B、RDMA、80GB pool、20GB SSD buffer、5 x NVMe RAID0；本地是单卡、TCP、本地单路径、小 pool。

产品推理：

Mooncake 数据说明 SSD offload 是实际系统方向，不只是 fio 压测。但产品侧不能只卖“盘快”，必须关心：

- cache manager 如何触发 eviction；
- offload write 是否稳定；
- read store tail 是否影响 TTFT；
- O_DIRECT / filesystem / GDS 路径是否稳定；
- pool / buffer / capacity 配置是否容易触发 space error；
- 多盘分片后最慢盘是否拖累整体 tail。

### 2.5 跨 SSD 和长稳态：短时冠军不等于长期服务冠军

资料来源：

- `docs/ai-ssd-boss-report-2026-06-15.md`
- `docs/kv-cache-final-selection-2026-06-10-zh.md`
- `docs/kv-cache-cross-vendor-2026-06-10-zh.md`
- `docs/kvcache-long-steady-state-2026-06-09-zh.md`

短测读带宽：

| 场景 | Biwin X570 | Seagate FC530 | ZhiTai Ti600 | WD SN570 |
|---|---:|---:|---:|---:|
| K4 8B x 16 users x 120s read BW | 3.14 GB/s | 2.34 GB/s | 2.46 GB/s | 1.55 GB/s |
| K5 70B x 4 users x 180s read BW | 2.77 GB/s | 2.09 GB/s | 1.93 GB/s | 1.49 GB/s |

长稳态：

| 场景 | Biwin X570 | Seagate FC530 | 结论 |
|---|---:|---:|---|
| K4 20min read BW | 1.92 GB/s | 1.91 GB/s | 基本持平 |
| K4 30min read BW | 1.57 GB/s | 1.54 GB/s | 基本持平 |
| 30min write P99 | 227.0 ms | 213.6 ms | Seagate 略好 |
| GC cliff time | 2.9 min | 8.1 min | Seagate 更晚进入 cliff |

GC cliff：

| SSD | Cliff time | Drop |
|---|---:|---:|
| Biwin X570 | 2.9 min | -40.6% |
| Seagate FC530 | 8.1 min | -32.0% |
| ZhiTai Ti600 | 5.6 min | -77.8% |
| WD SN570 | 7.8 min | -40.6% |

30 分钟 70B / long steady 相关观察：

| 指标 | 值 |
|---|---:|
| 平均读取带宽 | 2082 MB/s |
| 平均写入带宽 | 268 MB/s |
| 平均读取 IOPS | 17,049 |
| 平均写入 IOPS | 2,204 |
| 后期 read BW 下降 | 2981 MB/s -> 844 MB/s，约 -72% |
| await P95 上升 | 2.98 ms -> 8.01 ms，约 +169% |

工程解释：

1. 短测可能反映 SLC cache / fresh state / burst 能力。
2. 20-30 分钟后，GC、FTL、SLC 耗尽和写放大会改变排名。
3. KV cache 服务更关心 tail 和长期稳定，不只是平均 BW。
4. DRAM-less 或写 tail 弱的盘容易在 KV eviction 和 mixed R/W 下暴露风险。

产品推理：

AI SSD 规格必须区分：

| 能力 | 为什么重要 |
|---|---|
| Burst context load | 冷启动、短会话、首次长上下文加载 |
| Sustained context serving | 长会话、多轮 Agent、持续推理服务 |
| GC-aware read QoS | decode read 不能被后台 GC 和 writeback 阻塞 |
| Write tail control | eviction、checkpoint、RAG 更新会污染前台读 |
| Preconditioned performance | 生产环境不是 fresh empty drive |

## 3. 从数据到 AI SSD 预研方向的逻辑推理

### 3.1 推理链 A：为什么重点不是顺序峰值

事实：

1. 真实 block trace 显示主导 request size 是 128 KiB。
2. decode read 的 `>=100 MiB` LBA 大跳比例可达 89%-95%。
3. write 多数连续，read 才是随机压力主源。

中间判断：

1. KV cache offload 的瓶颈不是传统模型加载那种长顺序读。
2. 也不是传统数据库 4 KiB 小随机读。
3. 更接近 128 KiB 大块、大跨度、read-heavy、tail-sensitive 的随机读。

产品结论：

AI SSD 第一优先级应是：

- 128 KiB random read low tail；
- read-priority FTL / GC；
- 大跨度 LBA 访问下稳定 latency；
- 高并发下避免队列深度导致 P99 爆炸。

### 3.2 推理链 B：为什么长稳态是必测项

事实：

1. Biwin 短测读带宽领先，但 30 分钟后与 Seagate 收敛。
2. 多块消费级 SSD 都出现 GC cliff。
3. 30 分钟 long steady 中 await P95 上升，即使 I/O 量下降，单次操作仍变慢。

中间判断：

1. Fresh / burst 数据会高估 AI serving 能力。
2. KV cache 的持续写入、淘汰和读取会触发 SSD 内部 GC 与 SLC 耗尽。
3. 用户体验受 tail latency 和 stall window 影响，不只受平均吞吐影响。

产品结论：

AI SSD benchmark 必须包含：

- 30 / 60 / 120 分钟长稳态；
- preconditioning 后测试；
- GC cliff time；
- cliff drop；
- read/write P99/P999 drift；
- early / middle / late 三窗口指标。

### 3.3 推理链 C：为什么需要系统级 offload 测试

事实：

1. fio 可以跑出可重复 QD/P99，但不能代表真实 LBA adjacency 和 cache hit。
2. Mooncake 复测证明 SSD path 只有在 activation / read store / O_DIRECT / 文件增长都成立时，性能图才有 SSD 归因价值。
3. ShareGPT/BurstGPT 的真实 trace 与 synthetic fio 行为差异明显。

中间判断：

1. 设备好不等于系统收益好。
2. 系统收益取决于 cache manager、eviction、prefetch、CPU copy、文件系统、GDS/fallback、应用调度。
3. 只用 fio 可能误判产品方向。

产品结论：

AI SSD 测试必须是分层组合：

| 层级 | 测什么 | 工具 |
|---|---|---|
| 设备层 | 128 KiB random R/W、QD、P99/P999、preconditioning | fio |
| block trace 层 | 真实 LBA、request size、read/write split | bpftrace `block_rq_issue` |
| KV 系统层 | TTFT、cache hit、KV read/write、throughput | `kv-cache.py`、LMCache、SGLang |
| offload path 层 | SSD path 是否真正触发 | Mooncake/LMCache logs、O_DIRECT、GDS check |
| 生产近似层 | 多用户、多轮、多模型、RAG/checkpoint 混部 | end-to-end serving benchmark |

### 3.4 推理链 D：为什么 GDS / GPU-centric 路径值得预研

事实：

1. 非 GDS 路径通常是 SSD -> CPU DRAM -> GPU HBM，多一次 CPU bounce buffer。
2. KV cache 的价值在于减少 recompute，但如果数据搬运被 CPU copy、page cache、NUMA 干扰，SSD 能力无法充分转成 TTFT 收益。
3. Mooncake/LMCache/SGLang 等系统都在向分层 KV cache 和更直接的数据路径演进。

中间判断：

1. 随着 GPU 数量和 SSD 数量增加，CPU copy 可能成为瓶颈或 jitter 来源。
2. GDS / cuFile / hipFile 可以让 SSD 到 GPU memory 的路径更短，但必须验证是否真的 direct path，不能只看配置。
3. 高端 AI SSD 不应只作为块设备，还要适配 GPU-centric I/O。

产品结论：

GDS 方向应作为 P1/P2 预研：

- 验证 GDS vs non-GDS 的 TTFT、CPU utilization、read latency、tail；
- 测 `cuFile` direct path 和 POSIX fallback 的差异；
- 测多 NVMe path 与 GPU worker 绑定；
- 评估是否需要固件/驱动层优化 GPU direct read 的队列、对齐和 telemetry。

## 4. 建议的 AI SSD 预研方向

### P0：建立可信测试方法论

目标：避免再出现“配置名是 SSD 但实际没走 SSD path”或“模拟 LBA 当真实 LBA”的问题。

必须动作：

1. 所有 LBA 结论都使用 per-I/O `block_rq_issue` trace。
2. 所有 SSD offload benchmark 都必须通过 activation gate：
   - SSD root set；
   - offload enable；
   - offload files > 0；
   - read store > 0；
   - O_DIRECT 或 GDS direct path 证据；
   - 非 SSD 配置无 offload 文件污染。
3. 每组关键测试至少 3 次，报告 median / p95 / variance。
4. 使用独立测试盘，不在 root ext4 上做最终结论。
5. 固定 preconditioning 策略。

产出：

- AI SSD benchmark SOP；
- trace collection SOP；
- pass/fail gate；
- boss-facing 指标模板。

### P0：128 KiB random read tail benchmark

目标：把 KV cache 最核心的 decode read 压力转成可重复设备指标。

测试矩阵：

| 维度 | 取值 |
|---|---|
| Block size | 64 KiB、128 KiB、256 KiB |
| Read ratio | 90%、95%、100% |
| QD | 16、32、64、128 |
| 时长 | 10min、30min、60min |
| 状态 | fresh、preconditioned、near-full |

重点指标：

- read P50/P95/P99/P999；
- tail drift；
- IOPS/BW plateau；
- timeout / stall window；
- temperature / throttle；
- GC telemetry。

### P0：ShareGPT + BurstGPT 双 workload

目标：覆盖真实聊天和随机读 stress。

测试组合：

| Workload | 目标 |
|---|---|
| ShareGPT | realistic chat replay、prefix reuse、混合行为 |
| BurstGPT | 随机读压力、decode miss 风暴 |
| 分离 prefill/decode | 明确写入与读取路径差异 |

指标：

- KV storage read/write；
- block IOPS/BW；
- LBA jump distribution；
- TTFT / E2E latency；
- cache hit；
- per-round degradation；
- python/app I/O 占比。

### P1：长稳态与 GC cliff

目标：判断 AI SSD 是否适合 sustained serving。

测试要求：

- 30 / 60 / 120 分钟；
- 固定用户数，不让 autoscaler 混杂核心结论；
- 同时记录 iostat、block trace、SMART/NVMe telemetry；
- 分 early/mid/late 窗口出报告。

核心指标：

| 指标 | 意义 |
|---|---|
| GC cliff time | 多久后进入明显退化 |
| Cliff drop | 退化幅度 |
| Read P99 drift | 前台 decode 是否被污染 |
| Write P99 drift | eviction/checkpoint 是否稳定 |
| Stall duration | 用户是否会经历卡顿窗口 |
| Recovery time | GC 后是否能恢复 |

### P1：Mooncake / LMCache / SGLang 真实 offload

目标：从设备压力走向系统收益。

测试方向：

1. Mooncake SSD offload clean run：
   - 消除 `insufficient space`；
   - 扩大 pool / buffer；
   - 使用独立 SSD 目录；
   - 重复 3 次。
2. LMCache non-GDS vs GDS：
   - POSIX path；
   - cuFile direct path；
   - fallback detection；
   - CPU utilization 对比。
3. SGLang HiCache / vLLM tiering：
   - GPU/CPU/SSD 分层；
   - prefix cache；
   - eviction/prefetch 策略。

判断标准：

- SSD path 是否真实触发；
- SSD read 是否转化为 TTFT 改善；
- cache hit 是否来自 SSD 而不是 DRAM；
- CPU copy 是否成为瓶颈；
- 多轮后是否稳定。

### P1：跨 SSD / 跨产品族验证

目标：形成 AI SSD 产品规格，而不是某个消费盘经验。

建议样本：

| 类型 | 目的 |
|---|---|
| 高性能 TLC / DRAM SSD | 当前最接近 AI SSD 性能盘 |
| Enterprise TLC | 验证 sustained QoS 和掉电保护下的 tail |
| 高容量 QLC | 验证 cold context / RAG / long context capacity tier |
| DRAM-less SSD | 作为负例或低成本 overflow |
| 多盘 RAID0 / application sharding | 验证节点级扩展 |

输出：

- SSD AI workload score；
- burst score；
- sustained score；
- tail stability score；
- GC risk score；
- GDS readiness score。

## 5. 产品设计方向

### 5.1 固件 / 控制器方向

| 方向 | 设计目标 | 数据依据 |
|---|---|---|
| Read-priority GC | GC 和写回不能阻塞 decode read | read 是主要随机压力，decode tail 影响 TTFT |
| 128 KiB random 优化 | 提升 KV block 粒度下的 latency 和吞吐 | 实测主导 request size 是 128 KiB |
| Tail-aware scheduler | 控制 P99/P999，而不是只优化平均 | 长稳态和 QD1024 显示 tail 会爆炸 |
| 稳态 SLC / over-provisioning | 减少 cliff 和写放大 | 20-30min 测试出现 GC cliff |
| Mixed R/W isolation | eviction write 不污染 foreground read | write tail 和 GC 会影响 serving |
| 热/冷数据分层 | hot context 与 cold context 不同策略 | ShareGPT/BurstGPT 访问强度不同 |
| Multi-namespace / QoS | 多模型、多租户隔离 tail | AI serving 会多 worker 并发 |

### 5.2 设备规格方向

建议不要只写传统 SSD spec，应增加 AI SSD spec：

| 指标 | 建议表达 |
|---|---|
| 128 KiB random read P99 | preconditioned, QD32/QD64, 30min |
| 128 KiB mixed R/W P99 | 90/10、95/5、60/40 |
| Long steady drift | 30/60/120min throughput and P99 drift |
| GC cliff | cliff time、drop、recovery |
| GDS readiness | cuFile/hipFile direct path support and fallback detection |
| Telemetry | GC state、temperature、throttle、WA、SLC usage |
| QoS | multi-worker P99 isolation |
| Endurance | KV eviction write amplification under sustained serving |

### 5.3 系统集成方向

| 方向 | 目标 |
|---|---|
| GDS / GPU Direct path | 减少 CPU bounce buffer，降低 CPU overhead 和 jitter |
| io_uring / O_DIRECT path | 提供稳定低开销 non-GDS fallback |
| 多盘路径绑定 | GPU worker 与 NVMe path 对齐，减少争用 |
| cache-aware telemetry | 让上层知道 SSD 是否处于 GC / throttle / cliff 风险 |
| prefetch hint | 让 SSD/driver 知道即将读取的 KV block |
| eviction hint | 区分临时 KV、可丢弃 KV、长期上下文 |
| capacity tier | 高容量 QLC 用于 cold context，TLC/SLC-like 用于 hot context |

### 5.4 产品路线假设

| 路线 | 定位 | 核心卖点 | 风险 |
|---|---|---|---|
| AI SSD Performance Tier | GPU 服务器热 KV cache / decode read | 128 KiB random read tail、GDS、QoS | 成本高，需要系统生态配合 |
| AI SSD Capacity Tier | 长上下文、RAG、Agent memory、cold context | TB/$、稳定读、可接受 tail | QLC 写 tail 和 GC 风险 |
| AI SSD Developer Tier | AI PC / workstation / 小团队推理 | 本地 RAG、模型切换、代码 Agent、mixed R/W | workload 更杂，需要覆盖小文件/SQLite/checkpoint |
| AI SSD System Kit | SSD + driver + benchmark + telemetry | 让客户看到 TTFT/吞吐收益 | 需要软件投入 |

## 6. 建议的下一阶段实验计划

### 阶段 1：把现有结论变成可复现门禁

1. 修正所有报告中的 synthetic QD32 旧数值，统一为 30,545 IOPS / 2.85 GiB/s。
2. ShareGPT/BurstGPT 各跑 3 次，独立 SSD，输出 median 和方差。
3. 固定 preconditioning，再跑 fio QD sweep。
4. 产出一张 “AI SSD benchmark scorecard”。

### 阶段 2：做 clean Mooncake / LMCache offload

1. Mooncake 消除 `insufficient space` 后重测。
2. LMCache 测 non-GDS vs GDS。
3. 每次必须记录 activation gate。
4. 用 TTFT / cache hit / SSD read proof 三者共同判断收益。

### 阶段 3：进入产品样机方向

1. 选 2-3 类 SSD：
   - 高性能 TLC；
   - enterprise TLC；
   - 高容量 QLC。
2. 统一跑：
   - fio 128 KiB；
   - ShareGPT；
   - BurstGPT；
   - 60min long steady；
   - GDS / non-GDS。
3. 形成产品方向：
   - hot context performance SKU；
   - cold context capacity SKU；
   - AI PC developer SKU。

## 7. 可以对老板汇报的严谨说法

推荐表述：

> 我们已经把 AI SSD 的核心压力从“泛泛随机读写”收敛到更明确的 KV cache I/O 模式：128 KiB 级大块、read-heavy、decode 阶段大跨度随机读；写入多为连续或近连续，但会通过 GC 和写放大影响前台读尾延迟。BurstGPT 是更强的随机读压力，ShareGPT 是更真实的聊天 replay，fio 只能做设备压力标定。Mooncake 复测证明 SSD offload path 可以真实触发并带来本地收益趋势，但当前还有 storage warning，不能作为最终生产 benchmark。下一阶段应围绕 128 KiB random read tail、长稳态 GC、GDS 路径、多盘分片和真实 tiering 做产品级验证。

不建议表述：

| 不建议说法 | 原因 |
|---|---|
| “KV cache 就是 100% 随机大块 I/O” | 读写路径不同，写多数连续 |
| “fio 结果代表 KV cache offload 性能” | fio 没有真实请求语义和 cache hit |
| “Mooncake+SSD 性能已完全复现官方” | 本地环境差异大且有 storage warning |
| “某块消费盘就是最终 AI SSD 选型” | 还缺企业盘、多盘、GDS、长稳态和生产 tiering |
| “iostat 能证明 LBA 随机性” | 只能看聚合，不能看 per-request LBA |

## 8. 最终建议

### 对预研团队

优先把测试方法论固化。当前最有价值的不是继续堆更多图，而是把 evidence gate、repeatability、preconditioning、GDS/non-GDS、long steady 做成标准流程。

### 对产品团队

AI SSD 的产品定义应从以下能力开始：

1. 128 KiB random read tail；
2. 长稳态 GC 可预测；
3. read-priority firmware；
4. mixed R/W isolation；
5. GDS / GPU-centric readiness；
6. telemetry 可观测；
7. 多盘 QoS 和最慢盘风险控制。

### 对管理层

值得继续投入 AI SSD 预研，但不要过早承诺单盘型号或单一 benchmark 数字。更合理的阶段目标是：

1. 建立 AI SSD 专用测试标准；
2. 用真实 KV cache workload 验证产品指标；
3. 选择性能型和容量型两条路线；
4. 把 SSD 从“容量设备”定位为 LLM serving 的“context memory tier”。

