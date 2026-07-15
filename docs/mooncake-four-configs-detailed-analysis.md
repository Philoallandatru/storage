# Mooncake 四种配置详细分析

**文档日期:** 2026-07-15  
**数据来源:** `/home/ficus/llm/storage/docs/mooncake-ssd-offload-reproduction-and-io-analysis-2026-06-29.md`  
**图表位置:** `docs/assets/mooncake-ssd-offload-final-formal-20260629/`

## 概述

本文档详细解释 Mooncake SSD offload 测试中的四种配置、性能图表模式以及每轮（round 0-7）的具体行为。这些配置展示了从简单的 GPU-only KV cache 到多层缓存架构（GPU + Host Memory + Mooncake DRAM + SSD offload）的性能演进。

## 四种配置详解

### 1. GPU only

**含义：** KV cache 仅存储在 GPU 显存中，没有任何外部缓存层。

**配置特点：**
- 无 host memory 缓存
- 无 Mooncake memory pool
- 无 SSD offload

**预期行为：**
- Round 0 冷启动，cache hit = 0%
- Round 1-2 可能有少量命中（来自同批次请求间的复用）
- Round 3+ GPU 显存容量不足，大量 KV cache 被 evict 且无法恢复
- 最终 cache hit 率很低（测试结果：4.35%）

**性能结果：**
- Avg TTFT: 4.887s（最慢）
- Cache hit: 4.35%（最低）
- Input throughput: 3600.5 tok/s（最低）

**技术原因：**  
GPU 显存容量有限（RTX 5080 16GB），在多轮长上下文场景下，后续轮次的输入长度累积导致 KV cache 总量远超 GPU 显存。被 evict 的 KV cache 无处保存，下次需要时只能重新计算，因此 cache hit 率极低。

---

### 2. HiCache L1+L2

**含义：** 启用 SGLang HiCache 的两层缓存架构：L1 = GPU 显存，L2 = Host memory（CPU RAM）。

**配置特点：**
- L1 cache: GPU 显存
- L2 cache: Host memory
- 无 Mooncake memory pool
- 无 SSD offload

**预期行为：**
- Round 0 冷启动，cache hit = 0%
- Round 1-2 L2 开始缓存，hit 率显著提升（约 50%）
- Round 3+ Host memory 容量仍然有限，hit 率逐渐下降但优于 GPU only
- 最终 cache hit 率约 20.36%

**性能结果：**
- Avg TTFT: 4.253s（比 GPU only 快 13.0%）
- Cache hit: 20.36%（是 GPU only 的 4.7 倍）
- Input throughput: 3915.9 tok/s（提升 8.8%）

**技术原因：**  
Host memory 容量远大于 GPU 显存，可以存储更多被 evict 的 KV cache。当 GPU 显存不足时，KV cache 可以迁移到 host memory；后续需要时从 host memory 读回，避免重新计算。但 host memory 容量仍然有限，在 8 clients × 8 rounds × 3072 tokens 的累积压力下，后期仍会出现 cache miss。

---

### 3. +Mooncake

**含义：** HiCache L1+L2 基础上，增加 Mooncake DRAM memory pool 作为额外缓存层。

**配置特点：**
- L1: GPU 显存
- L2: Host memory
- L3: Mooncake memory pool（10GB DRAM，通过 TCP localhost 访问）
- **无** SSD offload

**关键参数：**
```json
{
  "global_segment_size": "10GB",
  "protocol": "tcp",
  "master_server_address": "127.0.0.1:50051",
  "enable_ssd_offload": false,
  "standalone_storage": false
}
```

**预期行为：**
- Round 0-2 与 HiCache L1+L2 类似或略好
- Round 3+ Mooncake pool 开始发挥作用，但 10GB 容量在累积压力下仍会填满
- Pool 满后必须 evict，被 evict 的 KV cache 无法恢复
- 最终 cache hit 率约 23.84%

**性能结果：**
- Avg TTFT: 4.151s（比 HiCache L1+L2 快 2.4%）
- Cache hit: 23.84%（略高于 HiCache L1+L2）
- Input throughput: 3981.8 tok/s（提升 1.7%）

**技术原因：**  
Mooncake memory pool 提供了额外的 DRAM 缓存空间。在前几轮中，10GB pool 可以容纳大量 KV cache，hit 率接近或优于 HiCache L1+L2。但从 round 3 开始，累积的 KV cache 总量超过 pool 容量，Mooncake master 开始触发 eviction（测试中观察到 10,475 次 EVICT-TRIGGER）。

**关键限制：** 一旦 Mooncake DRAM pool 满了，被 evict 的 KV cache 就彻底丢失了，因为没有 SSD offload 层来持久化这些数据。

---

### 4. +Mooncake+SSD

**含义：** Mooncake 配置基础上，启用 SSD offload，将被 evict 的 KV cache 写入 SSD 并支持后续读回。

**配置特点：**
- L1: GPU 显存
- L2: Host memory  
- L3: Mooncake memory pool（10GB DRAM）
- **L4: SSD offload**（NVMe SSD，通过文件存储实现持久化）

**关键参数：**
```json
{
  "global_segment_size": "10GB",
  "protocol": "tcp",
  "master_server_address": "127.0.0.1:50051",
  "enable_ssd_offload": true,
  "ssd_offload_path": "/mnt/ai_ssd0/mooncake_ssd0/file_storage"
}
```

**额外环境变量：**
```bash
MOONCAKE_ENABLE_SSD_OFFLOAD=true
MOONCAKE_OFFLOAD_FILE_STORAGE_PATH=/mnt/ai_ssd0/mooncake_ssd0/file_storage
MOONCAKE_OFFLOAD_LOCAL_BUFFER_SIZE_BYTES=2147483648  # 2 GiB local buffer
MOONCAKE_OFFLOAD_USE_URING=1  # 使用 io_uring 加速
```

**预期行为：**
- Round 0 冷启动，cache hit = 0%
- Round 1-2 与 +Mooncake 类似（pool 未满）
- **Round 3+ 显著分化：** pool 满后，被 evict 的 KV cache 写入 SSD；后续需要时从 SSD 读回
- 维持高 cache hit 率（测试结果：67.76%）

**性能结果：**
- Avg TTFT: 3.436s（比 +Mooncake 快 17.2%，比 GPU only 快 29.7%）
- Cache hit: 67.76%（是 +Mooncake 的 2.8 倍，是 GPU only 的 15.6 倍）
- Input throughput: 4469.9 tok/s（比 +Mooncake 提升 12.3%，比 GPU only 提升 24.1%）

**技术原因：**  
SSD offload 是多层缓存架构的"安全网"。当 Mooncake DRAM pool 容量不足时，不是简单地丢弃 KV cache，而是通过文件存储将其写入 SSD（测试中写入了 5,402 个文件，共 41 GiB）。后续请求需要这些 KV cache 时，可以从 SSD 读回（测试中观察到 52 次 offload read events），虽然读 SSD 比读 DRAM 慢，但远快于重新计算整个 prefill。

**SSD 激活证据：**
- ✅ Storage root directory 已设置
- ✅ `IsEnableOffloading result: true`
- ✅ 5,402 个 offload 文件（41 GiB）
- ✅ 52 次 offload read events
- ✅ 1,341 次 O_DIRECT file opens
- ✅ iostat 峰值：551.71 MB/s write, 205.69 MB/s read

---

## TTFT 图表分析

**图表位置：** `docs/assets/mooncake-ssd-offload-final-formal-20260629/02_per_round_performance_local.png`

### 整体趋势

所有配置的 TTFT 在 round 0 时都较低（约 0.5s），然后随着轮次增加而上升。这是因为：
1. **上下文累积：** 每轮增加 3072 tokens，后续轮次的 prefill 输入长度更长
2. **排队效应：** 8 个并发 clients，后期请求更容易排队
3. **缓存压力：** 后期缓存层逐渐填满，eviction 和 cache miss 增加

### 为什么 +Mooncake+SSD 的 TTFT 从 round 3 开始显著更低

**关键观察：** `+Mooncake+SSD` 和 `+Mooncake` 在 round 0-2 时曲线接近，但从 **round 3** 开始明显分化。

| Round | +Mooncake Avg TTFT | +Mooncake+SSD Avg TTFT | 差异 |
|---:|---:|---:|---|
| 0 | 0.520s | 0.522s | 基本相同 |
| 1 | 0.799s | 0.781s | 基本相同 |
| 2 | 1.059s | 1.026s | 基本相同 |
| **3** | **3.876s** | **2.743s** | **SSD 开始优势明显** |
| 4 | 6.756s | 5.884s | SSD 快 12.9% |
| 5 | 6.014s | 5.076s | SSD 快 15.6% |
| 6 | 5.348s | 3.787s | SSD 快 29.2% |
| 7 | 9.849s | 7.667s | SSD 快 22.2% |

**技术解释：**

1. **Round 0-2：Pool 未满阶段**
   - 此时 10GB Mooncake pool 容量充足
   - 两种配置都能将 KV cache 保存在 DRAM 中
   - SSD offload 尚未发挥作用
   - TTFT 相近是合理的

2. **Round 3：临界点**
   - 累积的 KV cache 总量开始超过 10GB pool 容量
   - **+Mooncake：** 开始大量 evict，被 evict 的 KV cache 丢失
   - **+Mooncake+SSD：** 被 evict 的 KV cache 写入 SSD，可以读回
   - TTFT 差异从这里开始显著拉开

3. **Round 4-7：SSD 优势期**
   - Pool 持续处于满负荷状态
   - **+Mooncake：** 持续 evict + cache miss + 重新计算 → TTFT 高
   - **+Mooncake+SSD：** SSD read 虽然比 DRAM 慢，但远快于重新计算 → TTFT 低

**量化证据：**
- +Mooncake 在 round 3-7 的平均 TTFT：6.369s
- +Mooncake+SSD 在 round 3-7 的平均 TTFT：4.831s
- **SSD 使后期 TTFT 降低 24.1%**

---

## Cache Hit Rate 图表分析

**图表位置：** 同上，`02_per_round_performance_local.png` 中的 cache hit 曲线

### 整体模式

| Config | R0 | R1 | R2 | R3 | R4 | R5 | R6 | R7 | 平均 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GPU only | 0% | 18.75% | 16.66% | 9.37% | 6.35% | 0% | 0% | 0% | 4.35% |
| HiCache L1+L2 | 0% | 49.99% | 49.99% | 28.12% | 25.77% | 13.19% | 10.71% | 10.93% | 20.36% |
| +Mooncake | 0% | 49.99% | 66.65% | 28.12% | 15.00% | 24.99% | 19.04% | 10.93% | 23.84% |
| **+Mooncake+SSD** | **0%** | **49.99%** | **66.65%** | **74.98%** | **79.98%** | **71.51%** | **79.14%** | **57.08%** | **67.76%** |

### 为什么 +Mooncake+SSD 能维持 67.76% 的高命中率

**关键观察：**
1. Round 0 所有配置都是 0%（冷启动，符合预期）
2. Round 1-2 多数配置都能达到 50-66%（缓存层还未满）
3. **Round 3-6 出现显著分化：**
   - GPU only 和 HiCache L1+L2 持续下降
   - +Mooncake 出现波动但整体偏低（15-28%）
   - **+Mooncake+SSD 维持在 71-80%**

**技术解释：**

#### Round 0：冷启动
- 所有配置 cache hit = 0%
- 无任何 KV cache 可复用
- 这是初始状态，符合预期

#### Round 1-2：缓存建立期
- HiCache、Mooncake、Mooncake+SSD 的 hit 率都达到 50-66%
- 此时各层缓存容量充足，主要差异来自缓存策略而非容量限制
- +Mooncake 和 +Mooncake+SSD 在 round 2 都达到 66.65%（证明此时 SSD 尚未发挥独特作用）

#### Round 3-7：SSD 价值凸显

**+Mooncake（无 SSD offload）的困境：**
```
Round 3+: 累积 KV cache > 10GB pool
  ↓
Mooncake master 触发 eviction（测试中 10,475 次）
  ↓
被 evict 的 KV cache 永久丢失
  ↓
后续请求需要这些 KV cache → cache miss → 重新计算
  ↓
cache hit 率下降到 15-28%
```

**+Mooncake+SSD 的优势机制：**
```
Round 3+: 累积 KV cache > 10GB pool
  ↓
Mooncake master 触发 eviction
  ↓
被 evict 的 KV cache 写入 SSD（41 GiB，5,402 个文件）
  ↓
后续请求需要这些 KV cache:
  - 如果在 GPU/Host/Mooncake pool → 直接命中（最快）
  - 如果在 SSD → 从 SSD 读回（52 次 offload read events）
  ↓
cache hit 率维持在 71-80%（比 +Mooncake 高 2.8-5.3x）
```

#### Round 7：Hit 率下降到 57.08%

即使是 +Mooncake+SSD，round 7 的 hit 率也从 79.14% 下降到 57.08%。可能原因：
1. **SSD 容量压力：** 测试日志显示 86 次 `insufficient space` warning
2. **累积上下文过长：** 8 rounds × 3072 tokens = 24,576 tokens 累积输入
3. **并发排队：** 8 clients 同时请求，调度压力增大

但 57.08% 仍然远高于 +Mooncake 的 10.93%，说明 SSD offload 即使在极限压力下仍然有效。

---

## 每轮（Round 0-7）详细行为解析

### Round 0：冷启动阶段

**所有配置：**
- Cache hit: 0%
- TTFT: 0.52-0.54s（最低）
- 行为：首次请求，无任何 KV cache 可复用

**技术原因：**  
这是冷启动状态。无论多少层缓存架构，都无法在第一次请求时命中（因为还没有任何缓存可供命中）。TTFT 较低是因为输入长度最短（3072 tokens），无排队压力。

---

### Round 1：缓存初建

**HiCache / Mooncake / Mooncake+SSD：**
- Cache hit: ~50%
- TTFT: 0.78-0.80s

**GPU only：**
- Cache hit: 18.75%（显著更低）
- TTFT: 0.818s

**技术原因：**  
Round 1 的输入包含 round 0 的部分上下文。对于有 L2 (host memory) 或 Mooncake pool 的配置，round 0 的 KV cache 可以被保存下来并复用，因此 hit 率达到 50%。GPU only 受限于显存容量，只能复用部分，因此 hit 率较低。

---

### Round 2：缓存稳定期

**Mooncake / Mooncake+SSD：**
- Cache hit: 66.65%（最高）
- TTFT: 1.03-1.06s

**HiCache L1+L2：**
- Cache hit: 49.99%
- TTFT: 1.054s

**GPU only：**
- Cache hit: 16.66%（继续下降）
- TTFT: 1.211s

**技术原因：**  
Round 2 的上下文长度已经达到 3072×2 = 6144 tokens。+Mooncake 和 +Mooncake+SSD 依靠 10GB pool，可以缓存更多 KV cache，hit 率达到 66.65%。HiCache L1+L2 的 host memory 容量有限，hit 率维持在 50%。GPU only 显存严重不足，hit 率继续下降。

**关键观察：** +Mooncake 和 +Mooncake+SSD 的 hit 率完全相同（66.65%），证明此时 SSD offload 尚未发挥作用（pool 未满，无需 offload）。

---

### Round 3：分水岭（SSD 开始发挥作用）

**+Mooncake+SSD：**
- Cache hit: **74.98%**（跃升）
- TTFT: 2.743s

**+Mooncake：**
- Cache hit: 28.12%（骤降）
- TTFT: 3.876s

**HiCache L1+L2：**
- Cache hit: 28.12%
- TTFT: 3.627s

**GPU only：**
- Cache hit: 9.37%
- TTFT: 5.013s

**技术原因：**  
Round 3 是关键转折点。累积的 KV cache 总量开始超过 10GB Mooncake pool 容量。

- **+Mooncake：** Pool 满后开始 evict，被 evict 的 KV cache 丢失 → cache miss 增加 → hit 率骤降到 28.12%
- **+Mooncake+SSD：** Pool 满后将 evicted KV cache 写入 SSD，后续可以读回 → hit 率跃升到 74.98%

这是 SSD offload 价值的第一次显著体现。

---

### Round 4-6：SSD 优势稳定期

**+Mooncake+SSD：**
- Cache hit: 71.51% - 79.98%（稳定高位）
- TTFT: 3.79-5.88s

**+Mooncake：**
- Cache hit: 15.00% - 24.99%（低位波动）
- TTFT: 5.35-6.76s

**HiCache L1+L2：**
- Cache hit: 10.71% - 25.77%
- TTFT: 4.29-6.34s

**GPU only：**
- Cache hit: 0% - 6.35%
- TTFT: 6.30-11.18s

**技术原因：**  
这三轮是各配置性能稳定期。

- **+Mooncake+SSD：** SSD offload 机制成熟，持续写入和读回被 evict 的 KV cache（测试共写入 41 GiB，52 次读回），维持 70-80% hit 率
- **+Mooncake：** Pool 持续处于满负荷，只能依靠 DRAM pool 内的缓存，hit 率维持在 15-25%
- **HiCache L1+L2 / GPU only：** 随着上下文累积，缓存容量持续不足，hit 率进一步下降

**量化对比：**
- Round 4-6 平均 hit 率：+Mooncake+SSD 76.88% vs +Mooncake 20.34%
- **SSD 使 hit 率提升 3.8 倍**

---

### Round 7：极限压力

**+Mooncake+SSD：**
- Cache hit: 57.08%（下降但仍最高）
- TTFT: 7.667s

**+Mooncake：**
- Cache hit: 10.93%
- TTFT: 9.849s

**HiCache L1+L2：**
- Cache hit: 10.93%
- TTFT: 8.831s

**GPU only：**
- Cache hit: 0%
- TTFT: 12.463s（最高）

**技术原因：**  
Round 7 的累积上下文已达 3072×7 = 21,504 tokens，加上 8 个并发 clients，系统处于极限压力。

- **+Mooncake+SSD：** SSD 层也出现压力（86 次 `insufficient space`），hit 率从 79.14% 下降到 57.08%，但仍然是最高的
- **其他配置：** hit 率已降到 0-10.93%，TTFT 显著升高

即使在极限压力下，+Mooncake+SSD 的 hit 率仍是 +Mooncake 的 5.2 倍，证明 SSD offload 在高压场景下的价值。

---

## 技术总结

### 为什么需要多层缓存架构

| 层级 | 容量 | 延迟 | 适用场景 |
|---|---|---|---|
| L1: GPU 显存 | 小（16GB） | 最低 | 热点 KV cache |
| L2: Host memory | 中（64-256GB） | 低 | 次热 KV cache |
| L3: Mooncake pool | 中（10-80GB） | 低-中 | 扩展缓存池 |
| L4: SSD offload | 大（TB 级） | 中 | 冷 KV cache（远快于重新计算） |

每一层都有其价值：
- **L1-L2（HiCache）：** 解决单卡显存不足问题
- **L3（Mooncake）：** 提供额外的 DRAM 缓存池
- **L4（SSD offload）：** 作为"安全网"，避免 evicted KV cache 永久丢失

### SSD Offload 的核心价值

SSD offload 不是为了加速，而是为了**避免重新计算**。

**性能对比：**
- 从 SSD 读取 KV cache：~200 MB/s 读带宽
- 重新计算 prefill：需要完整的 Transformer 前向传播

即使 SSD 读取比 DRAM 慢 10-100 倍，仍然比重新计算快得多，因此可以显著降低 TTFT 并提高 throughput。

### 何时应该使用 SSD Offload

**适用场景：**
- ✅ 多轮对话（上下文累积）
- ✅ 长上下文输入（单次请求 > 8K tokens）
- ✅ 高并发（多个 clients 同时请求）
- ✅ KV cache 总量 > GPU + Host + Mooncake pool 容量

**不适用场景：**
- ❌ 单轮短对话（无缓存复用机会）
- ❌ 缓存容量充足（SSD 不会被触发）
- ❌ SSD I/O 成为瓶颈（需要优化 I/O 栈或使用更快的 SSD）

---

## 参考图表

1. **整体性能对比：** `docs/assets/mooncake-ssd-offload-final-formal-20260629/01_overall_performance_local.png`
2. **每轮性能曲线：** `docs/assets/mooncake-ssd-offload-final-formal-20260629/02_per_round_performance_local.png`
3. **I/O 证据图表：** `docs/assets/mooncake-ssd-offload-final-formal-20260629/03_io_evidence_local.png`

---

**文档结束**
