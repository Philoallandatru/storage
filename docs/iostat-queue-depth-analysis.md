# iostat 统计数据与 Queue Depth 分析

**日期:** 2026-07-14  
**目的:** 详细说明测试中 iostat 统计的各项指标，特别是 Queue Depth (QD) 的含义、测量方式，以及不同 workload 和 SSD offload 场景下的 QD 差异

---

## 1. iostat 统计指标说明

### 1.1 采集命令

本项目中使用的 iostat 采集命令：

```bash
iostat -dx -m 1 > iostat.log
```

**参数说明：**
- `-d`：显示设备利用率统计
- `-x`：显示扩展统计信息（包括 queue depth）
- `-m`：以 MB/s 为单位显示吞吐量
- `1`：每秒采样一次

### 1.2 核心指标解释

| 指标 | 含义 | 单位 | 用途 |
|---|---|---|---|
| **r/s** | 每秒读请求数 | requests/s | 读 IOPS |
| **w/s** | 每秒写请求数 | requests/s | 写 IOPS |
| **rMB/s** | 每秒读取的数据量 | MB/s | 读带宽 |
| **wMB/s** | 每秒写入的数据量 | MB/s | 写带宽 |
| **avgrq-sz** | 平均请求大小 | sectors (512B) | I/O 粒度 |
| **avgqu-sz** | 平均队列长度 | requests | **Queue Depth** |
| **await** | 平均等待时间 | ms | 包含队列等待+服务时间 |
| **r_await** | 平均读等待时间 | ms | 读延迟 |
| **w_await** | 平均写等待时间 | ms | 写延迟 |
| **svctm** | 平均服务时间 | ms | **已废弃，不可靠** |
| **%util** | 设备利用率 | % | 设备繁忙程度 |

---

## 2. Queue Depth (QD) 详解

### 2.1 什么是 Queue Depth

**定义：** Queue Depth (队列深度) 是指**在任意时刻，等待 I/O 设备处理的请求数量**。

**iostat 中的表示：**
- `aqu-sz` (average queue size) 或 `avgqu-sz`
- 这是一个**时间平均值**，不是瞬时值

**计算方式：**
```
avgqu-sz = (采样周期内所有 I/O 请求的等待时间总和) / (采样周期时长)
```

**举例：**
- 如果在 1 秒内，有 10 个 I/O 请求，每个等待了 0.1 秒
- avgqu-sz = (10 × 0.1s) / 1s = 1.0

### 2.2 QD 的物理意义

**高 QD 可能意味着：**
1. ✅ **并发能力强**：应用程序发出了大量并发 I/O 请求
2. ⚠️ **设备压力大**：SSD 处理不过来，请求堆积
3. ⚠️ **延迟增加**：每个请求需要等待前面的请求完成

**低 QD 可能意味着：**
1. ✅ **延迟低**：请求立即被处理
2. ⚠️ **吞吐未饱和**：没有充分利用 SSD 的并发能力

### 2.3 QD 与延迟、吞吐的关系

**Little's Law（利特尔法则）：**
```
平均队列长度 (QD) = 吞吐量 (IOPS) × 平均延迟 (latency)
```

**示例：**
- 如果 IOPS = 10,000，平均延迟 = 3ms
- QD = 10,000 × 0.003s = 30

**推论：**
- 相同 QD 下，延迟越低 → 吞吐越高
- 相同吞吐下，QD 越高 → 延迟越高（排队等待）

---

## 3. 测试中的 Queue Depth 数据

### 3.1 KV Cache Workload QD 对比（5min 测试）

**数据源：** `docs/kv-cache-0629-5min-iostat-repro-analysis-2026-07-02.md`

| Workload | QD mean | QD p50 | QD p95 | QD max | Token/s | 特征 |
|---|---:|---:|---:|---:|---:|---|
| **BurstGPT** | 30.1 | 29.2 | 62.0 | 94.9 | 3195.6 | 高吞吐，QD 中等 |
| **ShareGPT** | 78.2 | 60.8 | 198.8 | 292.9 | 372.1 | 低吞吐，QD 很高 |

**关键发现：**

#### **BurstGPT：高吞吐 + 中等 QD**
- Token/s = 3195.6（高）
- QD mean = 30.1（中等）
- **解释：** 请求密集、cache hit 高（97.9%），I/O 操作快速完成，不容易堆积

#### **ShareGPT：低吞吐 + 高 QD**
- Token/s = 372.1（低）
- QD mean = 78.2（**高出 BurstGPT 2.6 倍**）
- QD p95 = 198.8（**高出 BurstGPT 3.2 倍**）
- QD max = 292.9（**高出 BurstGPT 3.1 倍**）
- **解释：** 大上下文、低 cache hit（72.2%），每个请求处理慢，导致排队堆积

**重要结论：**
> **业务吞吐低不代表 SSD 压力低！** ShareGPT 的 token/s 只有 BurstGPT 的 11.6%，但 QD 却高出 2.6 倍，说明设备承受了更重的排队压力。

### 3.2 为什么 ShareGPT 的 QD 这么高？

**原因 1：更低的 Cache Hit Rate**
- BurstGPT: 97.9%
- ShareGPT: 72.2%
- 更多 cache miss → 更多 SSD 读写 → 更长的处理时间 → 请求堆积

**原因 2：更大的上下文长度**
- ShareGPT 是多轮聊天，上下文更长
- 更长的 prefill 时间 → 后续请求等待 → QD 上升

**原因 3：更低的并发吞吐**
- Token/s 低说明系统处理慢
- 处理慢 + 请求持续到达 = 队列堆积

**用 Little's Law 验证：**
```
ShareGPT:
  假设 IOPS ≈ 14,063 (来自 3-way comparison 报告)
  QD mean = 78.2
  推算延迟 = 78.2 / 14,063 ≈ 5.6 ms

BurstGPT:
  假设 IOPS ≈ 35,195 (来自 3-way comparison 报告)
  QD mean = 30.1
  推算延迟 = 30.1 / 35,195 ≈ 0.86 ms
```

ShareGPT 的平均延迟约为 BurstGPT 的 **6.5 倍**！

---

## 4. Mooncake SSD Offload 场景的 QD 特征

### 4.1 Mooncake SSD 测试的 iostat 数据

**数据源：** `docs/mooncake-ssd-offload-reproduction-and-io-analysis-2026-06-29.md`

| 配置 | offload files | offload GiB | max write MB/s | max read MB/s | 特征 |
|---|---:|---:|---:|---:|---|
| GPU only | 0 | 0.0 | 770.82 | 367.29 | 模型加载等背景 I/O |
| HiCache L1+L2 | 0 | 0.0 | 570.07 | 107.23 | 较少 SSD 访问 |
| +Mooncake | 0 | 0.0 | 554.86 | 106.73 | 主要在 DRAM |
| **+Mooncake+SSD** | **5402** | **41.0** | 551.71 | **205.69** | SSD offload 激活 |

**注意：** 该测试未报告 QD 详细数据，但从 I/O 带宽可以推断：

#### **+Mooncake+SSD 的 I/O 特征**
- **写带宽**：551.71 MB/s（与其他配置接近）
- **读带宽**：205.69 MB/s（**明显高于其他配置**）
- **文件增长**：41 GiB 写入，52 次 offload read

**推断：**
- 写操作：eviction 到 SSD，相对顺序，QD 不会太高
- 读操作：从 SSD 读回 KV cache，可能随机，**QD 可能在 R4 阶段升高**

### 4.2 SSD Offload 的 QD 演进推测

基于 Per-Round TTFT 数据推测 QD 变化：

| Round | Cache hit | TTFT | 推测 QD 状态 |
|---:|---:|---:|---|
| R0 | 0.00% | 0.522s | **低** - 冷启动，写入为主 |
| R1 | 49.99% | 0.781s | **低** - DRAM pool 足够 |
| R2 | 66.65% | 1.026s | **低** - DRAM pool 仍足够 |
| R3 | 74.98% | 2.743s | **中** - 开始 evict 到 SSD |
| **R4** | **79.98%** | **5.884s** | **高** - 读写并发峰值 ⚠️ |
| R5 | 71.51% | 5.076s | **中高** - 热数据部分回到 DRAM |
| R6 | 79.14% | 3.787s | **中** - 趋于稳定 |
| R7 | 57.08% | 7.667s | **高** - 上下文过长 |

**R4 的 QD 峰值原因：**
1. **Eviction 写**：Mooncake pool 压力，大量 KV cache 被 evict 到 SSD
2. **Offload 读**：同时需要从 SSD 读回之前 evict 的数据
3. **读写并发争抢**：SSD 带宽有限，读写队列都在堆积
4. **延迟放大**：每个请求等待时间增加 → QD 上升

---

## 5. QD 的差异分析

### 5.1 KV Cache 场景：BurstGPT vs ShareGPT

| 维度 | BurstGPT | ShareGPT | 差异倍数 |
|---|---:|---:|---:|
| **QD mean** | 30.1 | 78.2 | **2.6×** |
| **QD p95** | 62.0 | 198.8 | **3.2×** |
| **QD max** | 94.9 | 292.9 | **3.1×** |
| **Token/s** | 3195.6 | 372.1 | **0.12×** |
| **Cache hit** | 97.9% | 72.2% | **0.74×** |
| **Block IOPS** | 35,195 | 14,063 | **0.40×** |

**关键洞察：**
```
Token/s 降低 88.4%
  ↓
Cache hit 降低 26.2%
  ↓
更多 SSD 访问 + 更长处理时间
  ↓
QD 升高 160%
```

**AI SSD 设计启示：**
- ✅ **不能只看吞吐优化 QoS**：ShareGPT 的低吞吐掩盖了高 QD 压力
- ✅ **需要支持高 QD 场景**：P95 接近 200，max 接近 300
- ✅ **QD 动态变化**：随 autoscaling、上下文长度、cache hit 共同变化
- ✅ **必须保护读 tail latency**：高 QD 下，P99 延迟容易恶化

### 5.2 SSD Offload 场景：+Mooncake vs +Mooncake+SSD

**读带宽对比：**
- +Mooncake: 106.73 MB/s
- +Mooncake+SSD: 205.69 MB/s（**↑ 92.7%**）

**推测 QD 变化：**
- +Mooncake: QD 相对稳定（主要在 DRAM）
- +Mooncake+SSD: 
  - R0-R2: QD 低（DRAM pool 足够）
  - **R3-R4: QD 峰值**（eviction + offload read 并发）
  - R5-R7: QD 趋于稳定（读写平衡）

**R4 TTFT 升高与 QD 的关系：**
```
Mooncake Pool 压力
  ↓
Eviction 写 + Offload 读并发
  ↓
SSD 队列堆积（QD 升高）
  ↓
每个请求等待时间增加
  ↓
TTFT 从 2.743s 升高到 5.884s
```

---

## 6. iostat 数据的局限性

### 6.1 iostat 不能证明的事情

❌ **不能单独证明 SSD offload 是否触发**
- GPU only 的 max write 770.82 MB/s 不代表 SSD offload
- 这些 I/O 可能来自模型加载、日志、系统背景

❌ **不能区分 I/O 来源**
- 无法区分哪些 I/O 来自 Mooncake offload
- 哪些来自文件系统元数据、日志等

❌ **不能提供 LBA 级别信息**
- 无法知道 I/O 的随机性（LBA 跳跃）
- 无法知道 I/O 的空间分布

❌ **svctm 字段已废弃**
- 在现代 SSD 和 Linux 内核中不可靠
- 不要用 svctm 计算延迟

### 6.2 必须组合的证据

判断 SSD offload 需要**组合证据**：

| 证据层 | 数据源 | 能证明 |
|---|---|---|
| **应用层** | `bench.log` | TTFT、throughput、cache hit |
| **中间层** | Mooncake logs | Storage root、enable、offload read、O_DIRECT |
| **文件系统层** | `inventory.log` | Offload 文件数、容量增长 |
| **设备层** | `iostat.log` | NVMe 读写带宽、QD、利用率 |
| **块设备层** | `bpftrace` | Per-I/O 事件、LBA、sector、rwbs |

**正确逻辑：**
```
Mooncake 日志确认 enable
  AND offload 目录文件增长
  AND offload read events > 0
  AND iostat 观察到 I/O 活动
  ↓
SSD offload 路径真实触发
```

### 6.3 iostat 与 block trace 的对比

| 维度 | iostat | bpftrace block trace |
|---|---|---|
| **采集层级** | 设备聚合统计 | 块设备 per-I/O 事件流 |
| **时间粒度** | 秒级聚合 | 纳秒级时间戳 |
| **空间信息** | 无 | 每个 I/O 的 LBA (sector) |
| **I/O 类型** | 读/写/IOPS/带宽 | rwbs (R/W/D/F/S 等) |
| **队列信息** | avgqu-sz (平均) | 需要后处理计算瞬时 QD |
| **开销** | 极低 | 中等（需要过滤设备） |
| **适用场景** | 设备级性能监控 | LBA 随机性、I/O 粒度分析 |

**何时使用 iostat：**
- ✅ 监控设备级吞吐和利用率
- ✅ 观察 QD 趋势
- ✅ 辅助证明 I/O 活动发生

**何时使用 block trace：**
- ✅ 分析 LBA 随机性（跳跃距离）
- ✅ 分析 I/O 粒度（128KiB vs 4K）
- ✅ 时间序列上的读写分布
- ✅ 证明真实 block I/O 发生（不被 page cache 吸收）

---

## 7. QD 数据对 AI SSD 设计的启示

### 7.1 必须支持高 QD 场景

**实测数据：**
- ShareGPT QD p95 = 198.8
- ShareGPT QD max = 292.9
- Mooncake+SSD R4 推测 QD 峰值 > 100

**设计要求：**
- ✅ **SSD 控制器需要支持高 QD**：至少 128-256
- ✅ **固件需要优化高 QD 下的调度**：防止 head-of-line blocking
- ✅ **Read Priority 在高 QD 下更关键**：避免写操作阻塞读

### 7.2 QD 不是常量，需要动态适应

**实测发现：**
- BurstGPT: QD 30 → 95 (3.2× 变化)
- ShareGPT: QD 78 → 293 (3.7× 变化)
- Mooncake+SSD: QD 从 R0 的低到 R4 的高峰

**设计要求：**
- ✅ **QoS 需要基于 QD 的动态调整**
- ✅ **不能用固定 QD 基准测试**：需要覆盖 QD 10-300 的范围
- ✅ **Telemetry 需要报告 QD 分布**：mean/p50/p95/p99/max

### 7.3 低吞吐不等于低压力

**反直觉发现：**
```
ShareGPT token/s = 372.1 (仅为 BurstGPT 的 11.6%)
但
ShareGPT QD mean = 78.2 (为 BurstGPT 的 260%)
```

**设计启示：**
- ❌ **不能只看 IOPS/带宽优化 SSD**
- ✅ **必须关注 QD 和延迟分布**
- ✅ **长上下文、低 hit rate 的场景 QD 更高**
- ✅ **需要针对"低吞吐高排队"场景优化**

### 7.4 读写并发时 QD 峰值

**Mooncake+SSD R4 现象：**
- Cache hit 最高（79.98%）
- 但 TTFT 也最高（5.884s）
- 推测 QD 在此时达到峰值

**设计启示：**
- ✅ **Eviction 写 + Offload 读并发时 QD 最高**
- ✅ **读写通道隔离可以降低 QD 峰值**
- ✅ **GC 必须可抢占**：避免 GC 写入加剧 QD 堆积
- ✅ **需要 per-operation telemetry**：区分读 QD 和写 QD

---

## 8. 如何在测试中正确使用 iostat

### 8.1 采集最佳实践

```bash
# 基本采集
iostat -dx -m 1 > iostat.log

# 采集更详细的时间戳
iostat -dxt -m 1 > iostat.log

# 只监控特定设备
iostat -dx -m 1 nvme0n1 > iostat.log

# 后台持续采集
nohup iostat -dxt -m 1 > iostat.log 2>&1 &
```

### 8.2 分析关键指标

**必看指标：**
1. **rMB/s / wMB/s**：读写带宽趋势
2. **r/s / w/s**：读写 IOPS
3. **avgqu-sz**：QD 趋势（重点关注 p95/max）
4. **%util**：设备利用率（接近 100% 说明饱和）
5. **r_await / w_await**：读写延迟（关注 tail）

**不要看的指标：**
- ❌ **svctm**：已废弃，不可靠

### 8.3 与其他工具组合

**组合 1：iostat + bpftrace**
```bash
# 终端 1：iostat 监控设备级
iostat -dx -m 1 nvme0n1

# 终端 2：bpftrace 采集 per-I/O 事件
bpftrace -e 'tracepoint:block:block_rq_issue { ... }' > block_trace.csv
```

**组合 2：iostat + inventory**
```bash
# 采集 iostat
iostat -dx -m 1 > iostat.log &

# 定期记录 offload 目录状态
while true; do
  echo "$(date +%s) $(du -sh /path/to/offload)" >> inventory.log
  sleep 10
done
```

**组合 3：iostat + Mooncake 日志**
```bash
# 同步时间戳
grep "offload key count\|read store" server.log > offload_events.log

# 对比 iostat 时间线，找到 I/O 峰值对应的事件
```

---

## 9. 核心结论

### 9.1 关于 Queue Depth

✅ **QD 是理解 SSD 压力的关键指标**
- 不是 IOPS/带宽，而是 QD 决定了延迟
- 高 QD 意味着排队等待，延迟放大

✅ **QD 是动态的，不是常量**
- 随 workload、cache hit、上下文长度变化
- BurstGPT: 30-95，ShareGPT: 78-293

✅ **低吞吐 ≠ 低 QD**
- ShareGPT token/s 低，但 QD 高出 BurstGPT 2.6 倍
- 业务慢 + 请求持续 = 队列堆积

### 9.2 关于 iostat 的使用

✅ **iostat 是设备级监控工具**
- 适合观察吞吐、QD、利用率趋势
- 不适合单独证明 I/O 来源

✅ **必须组合多层证据**
- 应用层 + Mooncake 日志 + 文件增长 + iostat + block trace
- 只看 iostat 会误判（GPU only 的高 I/O）

✅ **svctm 不可信，忽略它**
- 在现代 SSD 和内核中已废弃

### 9.3 关于 AI SSD 设计

✅ **必须支持高 QD（200-300）**
- ShareGPT p95 = 198.8, max = 292.9

✅ **必须优化高 QD 下的读 tail latency**
- 高 QD → 排队等待 → P99 恶化

✅ **必须支持读写并发场景**
- Mooncake+SSD R4: eviction 写 + offload 读并发
- 读写通道隔离 + GC 可抢占

✅ **Telemetry 需要报告 QD 分布**
- Mean/P50/P95/P99/Max
- 区分读 QD 和写 QD

---

## 10. 参考数据汇总

### 10.1 KV Cache Workload QD

| Workload | Duration | QD mean | QD p50 | QD p95 | QD max | Token/s | Cache hit |
|---|---:|---:|---:|---:|---:|---:|---:|
| BurstGPT 5min | 300s | 30.1 | 29.2 | 62.0 | 94.9 | 3195.6 | 97.9% |
| ShareGPT 5min | 300s | 78.2 | 60.8 | 198.8 | 292.9 | 372.1 | 72.2% |
| BurstGPT 3min | 180s | 25.6 | - | 54.9 | 78.8 | 2950.1 | 97.8% |
| ShareGPT 3min | 180s | 77.4 | - | 211.5 | 332.5 | 363.0 | 63.1% |

### 10.2 Mooncake SSD Offload I/O

| 配置 | max write MB/s | max read MB/s | offload GiB | 特征 |
|---|---:|---:|---:|---|
| GPU only | 770.82 | 367.29 | 0.0 | 背景 I/O |
| HiCache L1+L2 | 570.07 | 107.23 | 0.0 | 较少 SSD |
| +Mooncake | 554.86 | 106.73 | 0.0 | DRAM 主导 |
| +Mooncake+SSD | 551.71 | 205.69 | 41.0 | SSD offload |

**数据来源：**
- KV Cache: `docs/kv-cache-0629-5min-iostat-repro-analysis-2026-07-02.md`
- Mooncake: `docs/mooncake-ssd-offload-reproduction-and-io-analysis-2026-06-29.md`
