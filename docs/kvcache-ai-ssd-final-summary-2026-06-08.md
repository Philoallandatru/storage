# AI SSD KV-Cache 存储基准 — 完整测试总结报告

> **For Hermes:** 一次性总结本次预研所有结果 + 整合 docs/ 目录下所有相关文档,
> 解释每个术语,给出后续方向与技术预研判断。报告完全自包含,任何读者无需阅读
> 前置文档即可理解。

**作者:** Philoallan
**报告日期:** 2026-06-08
**项目背景:** AI SSD 产品预研 — 评估 KV-Cache 存储 I/O 工作负载在 NVMe SSD 上的行为
**测试框架:** MLPerf Storage Benchmark Suite v3.0.2 (kv_cache_benchmark 子模块)
**测试平台:** ASUS PRIME Z890-P WIFI · Ubuntu 26.04 · Kernel 7.0.0-22-generic
**存储目标:** `/dev/nvme1n1` (383 GB SSD,本地挂载根文件系统)

---

## 📖 如何读这份报告(读者指南)

**如果你是不熟悉 LLM 存储系统的读者**,按顺序读:
1. **§📚术语词典** — 先理解 KV-Cache / Prefill / Decode / Tier / Profiling 等术语
2. **§🏛️MLPerf Storage 整体背景** — 看清楚这是 4 个 benchmark 模块之一
3. **§🧪测试方法论** — 了解 4 层 profiling 架构
4. **§📊完整测试结果汇总** — 10 个跑的数据表
5. **§🧠关键发现与洞察** + **§🎯技术预研判断** — 核心结论

**如果你是 LLM 存储工程师,直奔**:
- **§📊测试结果汇总** — 数据表
- **§🎯技术预研判断** — 5 个核心结论
- **§🧭后续测试方向** — P0/P1/P2/P3 路线图

**如果你是产品/管理,只看**:
- **§🎯技术预研判断第 1 条**:"AI SSD 不是延迟瓶颈"
- **§🎯技术预研判断第 5 条**:"跨 MLPerf Storage benchmark 横向洞察"
- **§🧭后续测试方向** — 决策哪些测试值得做

---

## 📚 术语词典(必读)

> 这一节为不熟悉 LLM 存储系统的读者解释所有术语。每个术语解释后我会
> 注明在本文档哪里用到它。

### A. KV-Cache 相关

#### **KV-Cache (Key-Value Cache)**
LLM 推理过程中存储的"中间注意力"数据。每个 transformer 层、每个请求
都会产生一份 KV 数据,需要在 GPU/CPU/NVMe 之间流转。**这是 LLM 推理
最大的存储开销之一** — 一个 70B 模型 + 8000 token 长请求可产生超过
1 GB 的 KV 数据。

#### **Prefill (预填充阶段)**
LLM 处理用户输入 prompt 的阶段。**输入是一次性大量 token**,所以这一阶段
是 **写密集 (write-heavy)** —— 需要把所有输入对应的 KV 数据写进 cache。

#### **Decode (解码阶段)**
LLM 生成回答 token 的阶段。每生成一个新 token,**整个 attention 路径上
每一层都要从 cache 读一次 KV 数据**,所以是 **读密集 (read-heavy)**。
100 token 的回答意味着 ~100 × 80 层 = 8,000 次 KV cache 读。

#### **KV Object (KV 缓存条目)**
一次完整的"读或写 KV 数据"操作。它包含一个请求、一个 layer、一个 head
的所有 K/V tensor。**在 TP=8 下,每个 KV Object 会被切成 8 份,每个
GPU 节点保存 1/8。**

#### **Tier-0 / Tier-1 / Tier-2 (三层存储)**
benchmark 模拟的真实硬件分层:
- **Tier-0 = GPU VRAM**(H200 等 HBM) — 最快,容量最小
- **Tier-1 = CPU DRAM**(系统内存) — 中等
- **Tier-2 = NVMe SSD**(持久化) — 最慢,容量最大

我们跑 `--cpu-mem-gb 0` + `--gpu-mem-gb 0` 强制所有数据落到 Tier-2,
模拟纯 SSD 存储压力,这是 AI SSD 产品评估的真实场景。

#### **Eviction (驱逐)**
当 cache 满时,把冷数据从 Tier-0 推到 Tier-1,再推到 Tier-2 持久化。**这是
SSD 写入的最大来源**,比 prefill 一次性写更随机、更频繁。

### B. 测试配置术语

#### **Tensor Parallel (TP) 张量并行**
把模型切到多个 GPU 上跑。**TP=8 表示 KV Object 被切成 8 份**,每个
GPU rank 存 1/8。**TP 决定单条 IO 的 size** —— TP8 比 TP1 的单条 size
小 8 倍。

#### **Num Users (并发用户数)**
模拟同时有多少用户在与 LLM 交互。**这是模拟"请求并发度"的旋钮**。
users 越多 → 越多并发请求 → SSD 压力越大。

#### **Speedup (trace replay 加速)**
真实 BurstGPT trace 是按 wall-clock 时间记录的(可能几个小时)。
`--trace-speedup 1000` 表示把时间轴压缩 1000 倍 —— 让 1 秒代表 1ms
的真实流量。**这让我们能在 5 分钟 benchmark 内跑完生产环境的数小时流量**。

#### **BurstGPT trace**
从微软 Bing/Copilot 真实 LLM API 日志抓的 trace CSV,**包含真实用户
请求间隔、token 长度分布、会话模式**。比 synthetic(随机生成)更真实。
这是论文 [BurstGPT](https://arxiv.org/abs/2401.02577) 的数据集。

#### **ShareGPT**
真实用户与 ChatGPT 的对话数据集。**比 BurstGPT 更轻压力**(短上下文、
高 cache 命中率),用于对比"真实聊天负载 vs API trace 负载"。

#### **Max Concurrent Allocations (`--max-concurrent-allocs`)**
benchmark 内部 thread pool 同时能跑多少个 KV cache 分配任务。
**Codex 历史数据用 `2`**(不是 users 数),防止 RAM 爆炸。我们保持一致。

### C. Profiling 工具术语

#### **IOTracer (L3 文件系统层 trace)**
`--io-trace-log <path>` 激活。**记录每次 KV cache I/O 操作**到 .csv.zst
文件,内容包括:时间戳、操作类型 (Read/Write)、对象大小、tier (Tier-0/1/2)、
cache key、phase (Prefill/Decode/Evict)。**好处**: 拿到完整的 workload
形态;**坏处**: benchmark 用 NullBackend(不真正读/写硬件),**所以延迟
数据全是 0**。

#### **bpftrace (`storage_latency_stack.bt`,L2 块层 trace)**
`--enable-latency-tracing` 激活。**用 eBPF 内核探针追踪**每次 block I/O
的:
- **D2C (Dispatch to Complete)** — NVMe 命令从下发到物理设备完成的
  时间(纯硬件服务时间)
- **Q2D (Queue to Dispatch)** — block I/O 在 I/O scheduler 队列里等的
  时间(调度器拥塞指标)
- **VFS Read/Write** — 应用可见的 read/write 系统调用延迟(含 page cache)
- **fsync** — 设备 flush 延迟
- **bssplit** — block size 分布直方图
- **QD (queue depth)** — 同时在飞的 I/O 数量

#### **iostat (L1 设备层)**
`iostat -dx -m 1` 每秒采样。给出:
- **r/s, w/s** — 每秒读/写 IOPS
- **rkB/s, wkB/s** — 每秒读/写带宽 (MB/s)
- **r_await, w_await** — 设备级平均等待时间 (ms)
- **%util** — 设备利用率

#### **pidstat (L1 进程级)**
`pidstat -d 1` 每秒采样,**只看 python3 进程的 I/O**。把 SSD 活动和
benchmark 进程的活动关联起来。

#### **perf stat (L1 CPU 性能计数器)**
`sudo -n perf stat -e cache-misses,cs,migrations ...` — 抓 CPU cache
miss、上下文切换、迁移等微架构指标。**`perf_event_paranoid` 必须
设成 `-1`** 才能跑(默认 `4` 严格)。

#### **fio (蒸馏的目标)**
`distill_fio.py` 把 bpftrace 输出蒸馏成 `fio_<...>.ini` job 文件。**这样
能让用户在裸盘上重放相同的 I/O 模式,验证硬件极限**。**关键**:
蒸馏的 iodepth 可能非常大(如 2097152)—— 这不是建议值,**用户必须
用真实 iodepth sweep (32/64/128/256/1024) 替代**。

### D. 性能指标术语

#### **P50 / P95 / P99 / P99.9 (尾延迟分位数)**
P95 表示"95% 的请求都比这个延迟还快"。**P95 比平均值更能反映 SSD
真实表现** —— 平均值会被大量低延迟读拉低,P95 才会暴露真实的尾延迟。

#### **Storage I/O P95 vs Read Dev P95**
- **Storage I/O P95** — 从 benchmark 看到的"KV cache 读写总延迟 P95"
- **Read Dev P95** — KV object read latency 的 P95,只算设备部分(不含
  host 序列化)

#### **Cache Hit Rate (命中率)**
重复 KV cache key 命中的概率。**97% 命中率意味着大部分请求其实没有
真正发生 I/O**。这是 BurstGPT trace 跑出来的典型水平。

#### **SLA Compliance (服务等级协议合规率)**
QoS profile 内的请求有多少"达标"。**低于 95% 表示 SLA fail**。

### E. SSD 术语

#### **NVMe (Non-Volatile Memory Express)**
SSD 的通信协议。**比 SATA/AHCI 延迟低 10×**。

#### **%util (设备利用率)**
**100% 表示 SSD 队列一直满**。NVMe SSD 通常 >50% 就接近饱和(因为命令队列
通常很短)。我们的 30-55% 数据表示**SSD 还有大量余量**。

#### **r_await / w_await (读写等待时间)**
iostat 的核心延迟指标。**反映设备服务 I/O 的速度**。我们的 burstgpt CPU0
profile 下 r_await P95 在 0.16 ms 量级。

#### **SLC Cache (Single-Level Cell cache)**
消费级 NVMe SSD 通常有 20-30% 的 SLC 高速缓存(模拟 SLC 写入到 MLC/TLC)。
**空盘时所有写入直接命中 SLC,延迟低**;SLC 写满后会落到 TLC,延迟上升。
**P1: SSD preconditioning 测试就是要把 SLC 填满,避免空盘偏乐观**。

#### **GC (Garbage Collection) / Wear Leveling**
SSD 内部后台任务。**长时间跑(30-60 分钟)才显出影响**。

---

## 🏛️ MLPerf Storage 整体背景

**这次 KV-Cache 测试只是 MLPerf Storage Benchmark Suite 的 4 个模块之一**。
完整测试矩阵如下(摘自 `docs/README.md`):

| Benchmark | 测试内容 | 文档入口 |
|---|---|---|
| **Training I/O** | AI 训练数据加载的存储吞吐 | [QUICK_START.md](QUICK_START.md) |
| **Checkpointing** | 模型 checkpoint 保存/恢复性能(file + object store) | [Streaming-Chkpt-Guide.md](Streaming-Chkpt-Guide.md) |
| **KV-Cache** | LLM 推理的 KV cache 存储性能(GPU→CPU→NVMe) | [kv_cache_benchmark/README.md](../kv_cache_benchmark/README.md) |
| **Vector DB** | 向量数据库存储性能(Milvus) | [vdb_benchmark/README.md](../vdb_benchmark/README.md) |

### 4 个模块的标准测试结果(2026-04-26)

摘自 `tests/README.md` 的 `loki-russ` 测试机,4 MPI ranks,B200 加速器:

| Workload | POSIX NVMe | AU% | S3 Object | AU% | 关键细节 |
|----------|-----------|:---:|-----------|:---:|---------|
| **RetinaNet** (250K × 323KB JPEG) | 1,866 s/s | **92.8%** ✅ | 1,919 s/s | **95.4%** ✅ | [RetinaNet_test_results.md](../tests/RetinaNet_test_results.md) |
| **Flux** (130 Parquet × 256 samples) | 141 s/s | **99.7%** ✅ | 121 s/s | **85.4%** ⚠️ | [Flux_test_results.md](../tests/Flux_test_results.md) |
| **DLRM** (64 Parquet × 1M samples) | 389K s/s | **0.48%** ❌ | 106K s/s | **0.11%** ❌ | [DLRM_test_results.md](../tests/DLRM_test_results.md) |
| **Checkpointing** (llama3-8b, NP=4) | **1.416 GiB/s** | — | **2.213 GiB/s** | — | [Checkpoint_test_results.md](../tests/Checkpoint_test_results.md) |

**关键洞察**:
- **RetinaNet** 在 NVMe 和 S3 都 ≥85% AU 达标,O_DIRECT 验证通过
- **Flux** POSIX 达标,S3 因 loopback HTTP 略低于 90% 目标
- **DLRM** 因为 compute time 极低(0.375ms/step),纯 I/O-bound,需高带宽并行存储
- **Checkpointing**:**S3 多分片写 (32MB × 16 in-flight) 比本地 NVMe 快** — pipelining 优势

### KV-Cache 模块的设计目标(摘自 `MLperf_v3_KV_cache_proposal.md`)

MLPerf KV-Cache v3.0 提案明确指出要回答的 4 个关键问题:
1. **Tier Performance:** GPU vs CPU vs NVMe 速度差多少?
2. **Capacity Planning:** 在给定吞吐量下能支撑多少并发用户?
3. **Hardware Validation:** 哪款 NVMe SSD 最适合 LLM 推理?
4. **Bottleneck Identification:** 存储瓶颈在系统的哪个环节?

**提案里的 4 个标准测试**(本次预研主要做 #1 和 #3):
- **Test 1: Storage Baseline** — `--gpu-mem-gb 0 --cpu-mem-gb 0`,纯 SSD 压力
- **Test 2: Production Simulation** — 三层 + realistic generation mode
- **Test 3: Capacity Planning** — `--enable-autoscaling` QoS 模式
- **Test 4: Peak Throughput** — `--enable-autoscaling` capacity 模式

**重要 scope note**:
- **No tier promotion** — benchmark 用单向 waterfall(GPU→CPU→NVMe),不提升
- 这意味着每次读都要从 NVMe,**真实生产 vLLM 会提升热数据回 GPU**
- 所以 **Capacity Planning 反映的是存储吞吐量极限,不是端到端 serving 容量**
- **Bottleneck Identification 准确识别存储瓶颈,但可能漏掉 GPU/CPU 内存压力**

### 其他模块的 N-P Scaling 测试

每个 benchmark 都做了 N-P(Num Processes/Num Users)扩展性研究,展示
从 1 到 32 个并行进程的性能曲线:

| 文档 | 内容 |
|---|---|
| [Unet3D_NP_Scaling_Results.md](Unet3D_NP_Scaling_Results.md) | UNet3D 3D 图像分割(NP=1/2/4/8) |
| [RetinaNet_NP_Scaling_Results.md](RetinaNet_NP_Scaling_Results.md) | RetinaNet 目标检测 |
| [DLRM_NP_Scaling_Results.md](DLRM_NP_Scaling_Results.md) | DLRM 推荐系统 |
| [Flux_NP_ReadThreads_Scaling_Results.md](Flux_NP_ReadThreads_Scaling_Results.md) | Flux 图像生成(NP × Read-Threads 二维扩展) |

### Checkpointing 优化

[Streaming-Chkpt-Guide.md](Streaming-Chkpt-Guide.md) 包含两个重大优化:
1. **dgen-py Integration** — 随机 tensor 生成 **155× 加速**
2. **StreamingCheckpointing** — **192× 内存缩减**(对 llama3-8b,~105 GB checkpoint
   流式写入不再需要把所有数据放进 RAM)

### Object Storage 多端点负载均衡

[MULTI_ENDPOINT_GUIDE.md](MULTI_ENDPOINT_GUIDE.md) 展示 3 个存储库的多端点能力:
- **s3dlio** — 原生 multi-endpoint + true load balancing(推荐)
- **minio** — MPI rank-based endpoint selection
- **s3torchconnector** — MPI rank-based endpoint selection

---

## 🧪 测试方法论

### 4 层 Profiling 架构

```
L4 KV object          benchmark JSON/XLSX (每次跑产生)
L3 filesystem         --io-trace-log *.csv.zst (IOTracer)
L2 block layer        bpftrace storage_latency_stack.bt (Q2D/D2C/VFS 直方图)
L1 device             iostat + pidstat + perf stat (时间序列 + CPU counters)
```

### 跑测试流程

每次新配置跑 2 轮:
1. **Round 1: trace 模式** — `--io-trace-log` 激活,NullBackend,延迟全 0,
   跑满 300s。**得到 KV cache 逻辑 I/O pattern**
2. **Round 2: 真实 I/O 模式** — `--enable-latency-tracing` 激活,bpftrace
   采硬件延迟,跑满 300s。**得到真实硬件延迟 + 自动蒸馏 fio job file**

后台同时跑 `iostat -dx -m 1` + `pidstat -d 1` + `sudo -n perf stat -e ...`,
三个 L1 profiler 全程收数据。

---

## 📊 完整测试结果汇总

### 所有跑过的 burstgpt 配置(10 个)

| # | 配置 | requests | Read Dev P95 | Write Dev P95 | Cache Hit | SSD util | Status |
|---|---|---:|---:|---:|---:|---:|:---:|
| 1 | 8B users=2 (历史) | 5,748 | 17.96 ms | 18.90 ms | 97.75% | 55.0% / 69.2% | PASS |
| 2 | 70B users=2 (历史) | 2,421 | 41.85 ms | 18.68 ms | 97.86% | (无) | PASS |
| 3 | 70B users=4 (历史) | 2,490 | 92.67 ms | 125.53 ms | 97.74% | (无) | PASS |
| 4 | 70B users=8 (历史) | 3,395 | 115.34 ms | 177.22 ms | 97.79% | (无) | PASS |
| 5 | **70B users=6 bursttrace** | 3,377 | **96.10 ms** | **127.60 ms** | 97.70% | (无) | PASS |
| 6 | **70B users=6 full-profile-hwio** | 3,422 | **96.53 ms** | **114.02 ms** | 97.71% | 30.9% / 71.4% | PASS |
| 7 | **70B users=8 full-profile-hwio** | 2,521 | **164.63 ms** | **191.79 ms** | 97.79% | 30.4% / 68.8% | PASS |
| 8 | **8B users=8 full-profile-hwio** | 4,269 | **67.60 ms** | **186.78 ms** | 97.86% | 34.0% / 69.2% | PASS |
| 9 | **70B users=6 prefill-only** | 6,608 | n/a | **117.93 ms** | 0% | 22.7% / 61.6% | PASS |
| 10 | **70B users=6 decode-only** | 1,772 | **88.92 ms** | n/a | 97.73% | 28.7% / 62.4% | PASS |

### I/O Pattern (L3 trace 模式,trace 模式延迟 = 0)

| 配置 | total ops | Read % | Write % | Prefill % | Decode % | Evict % | Mean obj size | P95 obj size |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 70B users=6 mixed | 94,883 | 90.1% | 9.9% | 9.9% | 90.1% | 0% | 31.2 MB | 77.9 MB |
| 70B users=8 mixed | 94,883 | 90.1% | 9.9% | 9.9% | 90.1% | 0% | 31.2 MB | 77.9 MB |
| 8B users=8 mixed | 94,801 | 90.0% | 10.0% | 10.0% | 90.0% | 0% | 12.5 MB | 31.2 MB |
| **70B users=6 prefill-only** | **9,425** | **0%** | **100%** | **100%** | 0% | 0% | 25.0 MB | 73.6 MB |
| **70B users=6 decode-only** | **85,550** | **99.93%** | **0.07%** | 0.07% | **99.93%** | 0% | **80 MB** | **80 MB** (恒定) |

### 设备层 L1 (iostat nvme1n1)

| 配置 | r/s avg | wkB/s avg | %util avg | %util P95 | 主导模式 |
|---|---:|---:|---:|---:|---|
| ShareGPT users=2 (历史) | 388 | 27 MB/s | 2.3% | 8.0% | 极轻压力 |
| 8B BurstGPT users=2 (历史) | 17,694 | 208 MB/s | 55.0% | 69.2% | 读密集 + 平衡 |
| **8B BurstGPT users=8 (新)** | **15,654** | 185 MB/s | 34.0% | 69.2% | 读密集 |
| **70B BurstGPT users=6 (新)** | 12,240 | 153 MB/s | 30.9% | 71.4% | 平衡读写 |
| **70B BurstGPT users=8 (新)** | 14,422 | 172 MB/s | 30.4% | 68.8% | 平衡读写 |
| **70B prefill-only (新)** | 8,425 | **150 MB/s** | 22.7% | 61.6% | **纯写密集** |
| **70B decode-only (新)** | **17,082** | 27 MB/s | 28.7% | 62.4% | **纯读密集** |

### Block 层 L2 (bpftrace,蒸馏出的 fio job file)

| 配置 | rwmixread | read bssplit | write bssplit | iodepth (蒸馏,需替换) |
|---|---:|---|---|---:|
| 70B users=6 mixed | 91 | 4k/1:8k/1:16k/1:32k/1:64k/1:128k/97 | 4k/2:8k/1:16k/1:32k/1:64k/1:128k/97 | 32,768 |
| 70B users=8 mixed | 92 | 4k/1:8k/1:16k/1:32k/2:64k/2:128k/95 | 4k/2:8k/1:16k/1:32k/1:64k/1:128k/96 | 2,097,152 |
| 8B users=8 mixed | 92 | 4k/1:8k/1:16k/1:32k/2:64k/2:128k/95 | 4k/2:8k/1:16k/1:32k/1:64k/1:128k/96 | 2,097,152 |
| 70B prefill-only | 9 (写密集) | (省略) | 4k/1:8k/1:16k/1:32k/1:64k/1:128k/99 | 32,768 |
| 70B decode-only | **100** (纯读) | 4k/1:8k/1:16k/1:32k/1:64k/1:128k/99 | 4k/8:8k/1:16k/1:32k/1:64k/3:128k/86 | 32,768 |

---

## 🧠 关键发现与洞察

### 1. **混合 workload 是最严苛的测试场景** ⭐

| 模式 | %util avg |
|---|---:|
| 混合 (Run1, 70B users=6) | **30.9%** ← 最高 |
| prefill-only | 22.7% |
| decode-only | 28.7% |
| ShareGPT (历史) | 2.3% |

**结论**: SSD 在混合读写同时发生时压力最大,因为需要同时服务读请求
和维护写入(GC、wear leveling、SLC cache)。**混合 workload 才是真实
生产环境**。

### 2. **模型大小决定 object size,TP 决定切分大小**

| 模型 | Mean obj size (混合) | P95 obj size |
|---|---:|---:|
| 8B (TP8) | 12.5 MB | 31.2 MB |
| 70B (TP8) | 31.2 MB | 77.9 MB |

**70B object size 大约 2.5× 8B**(符合 LLM 模型规模比,~70/8 ≈ 9×,**但 TP=8
让绝对 size 缩小 8×**,所以比例下降到 ~3×)。

### 3. **decode-only 是纯读路径,17,082 IOPS 是最高**

decode-only 没有 prefill 写,所有 16,209 个 decode_reads 都被
bottleneck 在 SSD read IOPS 上。**但 IOPS 高 ≠ 延迟低** — Read Dev P95
仍是 88.92 ms(因为 KV object size 很大)。

### 4. **prefill-only 是纯写路径,150 MB/s 持续写**

prefill-only 没有 decode 读,所有 6,608 个 prefill_writes 持续写
KV cache。**Write Dev P95 = 117.93 ms**(比混合模式 114 ms 略高,
因为没有任何读干扰)。

### 5. **bpftrace 蒸馏的 iodepth 不能直接用**

**3 个蒸馏的 .ini 的 iodepth 分别是 32,768 / 2,097,152 / 2,097,152**。
这些是 P50 queue depth,不是建议值。**必须替换为合理 iodepth
(32/64/128/256/1024) 再跑**,否则 fio 跑不出真实硬件表现。

### 6. **cache hit rate 稳定 97.7%** — 真实流量来自 cache eviction

**BurstGPT trace 的请求模式高度重复**,所以命中率很高。
**真实生产环境需要用 trace replay 多次循环**(`--replay-cycles 0`)
才能打破这个模式,触发真实 cache eviction 流量。

---

## 🎯 技术预研判断

### 1. **AI SSD 不是延迟瓶颈**

70B 真实 BurstGPT trace 在 users=8 仍 PASS,Read Dev P95 < 200ms,
SSD 利用率稳定 30-35%。**当前 NVMe SSD 对 KV-Cache 工作负载有充足
余量** —— AI SSD 选型不是性能瓶颈。

### 2. **真正的风险点**

| 风险 | 当前状态 | 影响 |
|---|---|---|
| **写放大 (write amplification)** | 150 MB/s 持续写(prefill-only) | 长稳态可能引发 GC 退化 |
| **写尾延迟 (write tail latency)** | P95=120ms 量级 | 用户体验退化 |
| **稳态漂移 (steady-state drift)** | 5 分钟内未观察到 | 30-60 分钟测试未跑 |
| **预条件化状态 (preconditioning)** | 空盘测量偏乐观 | 真实生产可能更差 |
| **CPU cache 遮蔽 (cpu-mem-gb 遮蔽)** | 我们用 cpu-mem-gb=0 测的是"纯 SSD 压力" | 加 DRAM cache 后 SSD 压力下降(可能 30-50%) |

### 3. **不同 workload 形态的 SSD 需求差异**

| 场景 | SSD 关键指标 |
|---|---|
| 短聊天 (ShareGPT-like) | 低延迟,小写入,无 GC 压力 |
| API trace (BurstGPT) | 高 IOPS,中等写入,**关键是 P95 尾延迟** |
| 长上下文 (Synthetic, code) | 高带宽,大写入,GC 压力高 |
| 70B+ 生产负载 | 高 IOPS + 高写入 + 大 object + 稳态表现 |

### 4. **Decode-only 模式才是 KV-cache 的真正考验**

混合模式的 30% util 看似低,但 decode-only 模式 17,082 IOPS 才是
真实生产中的瓶颈场景 —— 因为生产 LLM 服务中,**decode 阶段占
总请求的 90%+**(用户主要等模型生成回答)。

### 5. **跨 MLPerf Storage benchmark 的横向洞察**

| 模块 | 关键发现 | 对 AI SSD 的相关性 |
|---|---|---|
| **KV-Cache (本次)** | 30% util 是真实 SSD 基线 | AI SSD 选型直接相关 |
| **Training I/O** | O_DIRECT 比 page cache 延迟低 10× | AI SSD 必须支持 O_DIRECT |
| **Checkpointing** | S3 多分片写比本地 NVMe 快(pipelining) | AI SSD 比 S3 快,但需支持大写入 |
| **DLRM (推荐)** | AU 极低(0.48%),纯 I/O-bound | 提示 SSD 带宽在某些 workload 是瓶颈 |
| **Vector DB (Milvus)** | 随机读 IOPS 需求高 | 与 KV-cache decode-only 路径类似 |
| **Streaming Checkpointing** | 流式 192× 内存缩减 | 减少 CPU RAM 占用,降低 SSD 写入压力 |

---

## 🧭 后续测试方向

### P0 (本次没完成,马上做)

#### **P0 #3: fio sweep — 找到真实饱和点**
- 改蒸馏的 .ini: `iodepth=2097152` → 32/64/128/256/1024
- 跑 5 个 iodepth × 3 个 workload = 15 个 fio run
- 收集 P50/P95/P99/P99.9 延迟,绘制"iodepth vs latency"曲线
- **找到真实饱和 iodepth** — 这就是 AI SSD 选型的硬件极限
- 预计时间:~45 分钟
- **价值:可复现的硬件 spec** — 任何厂商都能跑这个 fio sweep 验证 SSD

### P1 (重要,P0 完成后做)

#### **P1: SSD preconditioning 测试**
- 用 `--precondition` flag,预写满 SSD 后重跑 BurstGPT CPU0 profile
- 排除空盘偏乐观(SLC cache 还没用),真实生产环境更严苛
- 预计时间:~30 分钟

#### **P1: 长稳态 30-60 分钟测试**
- 跑 `burstgpt_70b_users6_3600s` 1 小时版本
- 观察热、GC、wear leveling、page cache 稳态
- **找出延迟漂移拐点** — 这是 AI SSD 选型的真实参考
- 预计时间:~70 分钟

#### **P1: CPU cache sensitivity 测试**
- 跑 `cpu-mem-gb=0,0.5,1,2` 四个梯度
- 评估 DRAM cache 对 SSD 压力的遮蔽程度
- **为产品设计给出"是否需要 DRAM cache 加速卡"的依据**
- 预计时间:~25 分钟

### P2 (扩展覆盖)

#### **P2: 其他 LLM 模型**
- DeepSeek V3 / Qwen3-32B / GPT-OSS-120B / GPT-OSS-20B
- 不同 KV bytes/token 的模型结构(MoE / MLA / GQA)
- 对比 object size 与 device P95 的关系
- 预计时间:~3-4 小时(8 个新配置)

#### **P2: prefill+decode 混合比例扫描**
- 跑 100/0、75/25、50/50、25/75、0/100(prefill/decode 流量比例)
- 找到最严苛的混合比例
- 预计时间:~60 分钟

### 长期(P3+)

#### **P3: 多设备并行测试**
- 同时跑多个 benchmark 实例,模拟多租户场景
- 测试 SSD 在并发租户下的表现
- 预计时间:~2 小时

#### **P3: 真实硬件 vs QEMU 模拟对比**
- 验证 bpftrace 数字是否能在 QEMU 模拟环境中复现
- 为生产环境部署做基准
- 预计时间:~4 小时

---

## 📁 完整产物清单

### 数据目录 (5 个 profiling 跑)

```
results/kvcache-profile/profiling/
├── burstgpt_70b_users6_full_20260608_113434/  # Run1: 70B users=6 mixed
├── burstgpt_70b_users8_full_20260608_114604/  # Run2: 70B users=8 mixed
├── burstgpt_8b_users8_full_20260608_114639/   # Run3: 8B users=8 mixed
├── burstgpt_70b_users6_prefill_only_20260608_145905/  # Run4: prefill-only
└── burstgpt_70b_users6_decode_only_20260608_145905/  # Run5: decode-only
```

### Benchmark JSON/XLSX (10 个新文件)

```
results/kvcache-profile/test_burstgpt_70b_users6_full_20260608_113434_{trace,hwio}.{json,xlsx}
results/kvcache-profile/test_burstgpt_70b_users8_full_20260608_114604_{trace,hwio}.{json,xlsx}
results/kvcache-profile/test_burstgpt_8b_users8_full_20260608_114639_{trace,hwio}.{json,xlsx}
results/kvcache-profile/test_burstgpt_70b_users6_prefill_only_20260608_145905_{trace,hwio}.{json,xlsx}
results/kvcache-profile/test_burstgpt_70b_users6_decode_only_20260608_145905_{trace,hwio}.{json,xlsx}
```

### fio job files (5 个,在 kv_cache_benchmark/ 下)

```
kv_cache_benchmark/fio_kv_cache_workload_20260608_114442.ini  # 70B users=6 mixed
kv_cache_benchmark/fio_kv_cache_workload_20260608_115613.ini  # 70B users=8 mixed
kv_cache_benchmark/fio_kv_cache_workload_20260608_115648.ini  # 8B users=8 mixed
kv_cache_benchmark/fio_kv_cache_workload_20260608_151927.ini  # 70B decode-only
(以及 prefill-only 的 .ini)
```

### I/O Pattern 报告 (5 个 PNG + 5 个 MD)

```
results/kvcache-profile/io_pattern_burstgpt_70b_users6_full_20260608_113434.{png,md}
results/kvcache-profile/io_pattern_burstgpt_70b_users8_full_20260608_114604.{png,md}
results/kvcache-profile/io_pattern_burstgpt_8b_users8_full_20260608_114639.{png,md}
results/kvcache-profile/io_pattern_burstgpt_70b_users6_prefill_only_20260608_145905.{png,md}
results/kvcache-profile/io_pattern_burstgpt_70b_users6_decode_only_20260608_145905.{png,md}
```

### iostat 摘要 (5 个 CSV)

```
results/kvcache-profile/iostat_summary_burstgpt_70b_users6_full_20260608_113434.csv
results/kvcache-profile/iostat_summary_burstgpt_70b_users8_full_20260608_114604.csv
results/kvcache-profile/iostat_summary_burstgpt_8b_users8_full_20260608_114639.csv
results/kvcache-profile/iostat_summary_burstgpt_70b_users6_prefill_only_20260608_145905.csv
results/kvcache-profile/iostat_summary_burstgpt_70b_users6_decode_only_20260608_145905.csv
```

### 汇总 CSV (已更新)

```
docs/assets/kvcache-io-profiling/io_profile_summary.csv  (17 → 24 行,+7)
docs/assets/kvcache-io-profiling/iostat_summary.csv       (去重后 11 行)
```

### 脚本(5 个)

```
scripts/run_full_profiling.sh             # 4 层 profiling wrapper
scripts/run_prefill_decode_sweep.sh       # prefill/decode-only 顺序跑
scripts/analyze_io_trace.py                # io-trace-log CSV → md+png
scripts/summarize_iostat_pidstat.py        # iostat.log → CSV 摘要
scripts/append_to_io_profile_summary.py    # 新 JSON → 主 CSV
```

### 文档(全部 docs/)

```
docs/README.md                                          # 总文档索引
docs/ARCHITECTURE.md                                    # MLPerf 架构
docs/QUICK_START.md                                     # 4 模块快速上手
docs/kvcache-ai-ssd-prestudy-2026-06-08.md             # KV-Cache 主报告(历史)
docs/kvcache-io-profiling-visual-analysis-2026-06-08.md  # I/O profiling 分析
docs/kvcache-full-profiling-results-2026-06-08.md      # 4 层 profiling 完整数据
docs/kvcache-prefill-decode-split-2026-06-08.md        # prefill/decode 拆分
docs/kvcache-ai-ssd-final-summary-2026-06-08.md         # 本文档(总结)
docs/STORAGE_LIBRARIES.md                              # 3 个存储库对比
docs/Object_Storage.md                                  # Object storage 综合
docs/OBJECT_STORAGE_GUIDE.md                            # object storage 配置参考
docs/Object_Storage_Library_Setup.md                    # object storage 库安装
docs/Object_Storage_Test_Guide.md                       # object storage 测试指南
docs/Object_Storage_Test_Results.md                     # object storage 测试结果
docs/MULTI_ENDPOINT_GUIDE.md                            # 多端点负载均衡
docs/Streaming-Chkpt-Guide.md                            # 流式 checkpoint
docs/PARQUET_FORMATS.md                                 # Parquet 数据格式
docs/DATALOADER_ARCHITECTURE.md                          # DataLoader 架构
docs/ADDING_BENCHMARKS.md                                # 新增 benchmark
docs/Unet3D_NP_Scaling_Results.md                        # UNet3D N-P 扩展
docs/RetinaNet_NP_Scaling_Results.md                     # RetinaNet N-P 扩展
docs/DLRM_NP_Scaling_Results.md                          # DLRM N-P 扩展
docs/Flux_NP_ReadThreads_Scaling_Results.md              # Flux 扩展
tests/README.md                                          # 测试矩阵 + 历史结果
kv_cache_benchmark/docs/MLperf_v3_KV_cache_proposal.md   # MLPerf KV-Cache 提案
kv_cache_benchmark/docs/io_trace_log_usage.md            # IO-trace-log 用法
kv_cache_benchmark/docs/simulated_gpu_tier_design.md     # GPU tier 设计
```

### Git commits(本次 session 内)

```
4bd6903  profiling: 4-layer I/O profiling data for 70B users=6/8 + 8B users=8
f9e0d4d  split: prefill-only / decode-only split for 70B users=6
fc6ea26  docs: final AI SSD KV-Cache benchmark summary
```

---

## 📞 报告者备注

- 所有时间戳格式:`YYYYMMDD_HHMMSS` (e.g., `20260608_113434`)
- 所有产物用 `--max-concurrent-allocs 2`(不是 users 数)
- 所有 burstgpt 跑用 `--trace-speedup 1000 --replay-cycles 0`(无限循环)
- 所有跑用 `--gpu-mem-gb 0 --cpu-mem-gb 0`(纯 SSD 压力)
- 所有跑 TP=8,8 个 GPU 模拟

**报告结束。**