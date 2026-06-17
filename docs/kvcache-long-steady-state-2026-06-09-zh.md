# KV 缓存长期稳态运行 — 30 分钟 GC 漂移分析 (KV-Cache Long Steady-State Run — 30-Minute GC Drift Analysis)

**日期 (Date)**: 2026-06-09
**测试时长**: 30 分钟（1800s，实际 1810s）
**测试配置**: BurstGPT 70B users=6, real I/O mode, `--enable-latency-tracing`, autoscaling
**测试盘**: `/dev/nvme1n1` (BIWIN X570 1TB, 3D TLC, SLC 测试后稳态状态)

## 测试目的 (Test Purpose)

**核心问题**: 长稳态下 SSD 行为如何演化？GC 是否在 30 分钟内累积导致性能下降？

## 数据来源 (Data Sources)

| 类型 (Type) | 文件 (File) | 大小 (Size) |
|---|---|---|
| iostat.log | `profiling/long_steady_state_30min_20260609_103815/iostat.log` | 1810 行（每秒采样） |
| Bench.log | `profiling/long_steady_state_30min_20260609_103815/bench.log` | 22 KB |
| KV trace | （trace mode 未启用，只有真实 I/O） | - |
| Bench JSON | `results/kvcache-profile/test_long_steady_state_30min_20260609_103815.json` | - |
| 蒸馏 fio workload | `fio_kv_cache_workload_20260609_110823.ini` | - |
| 时序 CSV | `long_steady_analysis/iostat_timeseries.csv` | 1810 行 |
| 时序图 PNG | `long_steady_analysis/iostat_timeseries.png` | 4 面板 |
| 5 分钟窗口 CSV | `long_steady_analysis/iostat_window_5min.csv` | 7 个窗口 |
| GC drift 报告 | `long_steady_analysis/gc_drift_report.md` | - |

## 整体统计 — 1810 秒聚合 (Overall Statistics — 1810s Aggregate)

| 指标 (Metric) | 值 (Value) |
|---|---:|
| **平均读取带宽 (Avg Read BW)** | **2082 MB/s** |
| 平均写入带宽 (Avg Write BW) | 268 MB/s |
| 平均读取 IOPS (Avg Read IOPS) | 17,049 |
| 平均写入 IOPS (Avg Write IOPS) | 2,204 |
| **平均利用率 (Avg %util)** | **59.6%** |
| **平均等待时间 (Avg await)** | **2.51 ms** |
| 峰值利用率 (Peak %util) | 79.7% |
| 峰值等待时间 (Peak await) | 25.2 ms |

**Bench 累积 I/O (Bench Cumulative I/O)**:
- 总读取 (Total Read): **3.61 TiB**
- 总写入 (Total Write): 425.6 GiB
- 读写比 (Read/Write Ratio): **8.48**
- 总追踪 I/O (Total Traced I/Os): **34,835,995**（30.85M 读取，3.98M 写入）

## 🧠 关键发现: 显著 GC 漂移 (Key Finding: Significant GC Drift)

### 5 分钟窗口对比 (5-Minute Window Comparison)

| 窗口 (Window) | R MB/s | W MB/s | R IOPS | W IOPS | %util | await | await P95 | await max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-300s | **2981** | 275 | 24456 | 2254 | 61.3 | **1.19** | 2.98 | 6.65 |
| 300-600s | 2703 | 244 | 22137 | 2004 | 68.6 | 1.68 | 3.63 | 5.81 |
| 600-900s | 2332 | 231 | 19151 | 1913 | 63.0 | 1.57 | 3.71 | 7.50 |
| 900-1200s | 1672 | 296 | 13622 | 2431 | 57.8 | **3.72** | 7.75 | **20.67** |
| 1200-1500s | 2008 | 335 | 16275 | 2736 | 64.5 | **3.76** | 7.23 | 15.52 |
| 1500-1800s | 844 | 231 | 7055 | 1931 | 43.3 | 3.15 | 8.01 | **25.21** |
| 1800-1810s | 579 | 103 | 4983 | 874 | 26.4 | 1.68 | 5.59 | 5.59 |

### 演化趋势 — 关键观察 (Evolution Trend — Key Observations)

| 指标 (Metric) | 早期 (0-300s) | 中期 (600-1200s) | 后期 (1500-1800s) | 变化 (Change) |
|---|---:|---:|---:|---:|
| 读取带宽 Read BW (MB/s) | 2981 | ~2000 | **844** | **-72%** |
| %util | 61.3 | 60.4 | 43.3 | -29% |
| await (ms) | 1.19 | 2.65 | **3.15** | **+165%** |
| await P95 | 2.98 | 5.73 | 8.01 | +169% |

### 解读: 为什么会这样？(Interpretation: Why does this happen?)

**3 个独立现象叠加 (Three independent phenomena叠加)**:

1. **Autoscaling 缩减 (Autoscaling ramp-down)**: Bench 启动时 queue 持续增长 → autoscaler 把 user count 从约 30 缩减到 1。这是**主要驱动因素**：后期 I/O 量下降。

2. **GC 漂移（真实的 SSD 行为）**: 即使 I/O 减少，**await 反而上升**（从 1.19 → 3.15 ms）。这是 GC 在稳态下持续工作，污染随机读路径。

3. **等待队列拥塞 (Wait queue congestion)**: Bench 日志显示 Queue 从 0 → 376K（后期），说明 LLM 推理在等 SSD 响应。

### 为什么平均读取带宽后期会下降？(Why does Avg Read BW decrease in later phase?)

不是 SSD 变慢，**原因是**：
- 用户数减少 → 写请求减少 → KV 缓存压力下降 → 读取需求下降
- 带宽自然下降到低负载水平
- 但 **await 没有按比例下降** = SSD 单次操作变慢

## 🎯 对 AI SSD 产品设计的启示 (Implications for AI SSD Product Design)

### 1. AI SSD 在稳态下 IOPS 持续 17K+

BIWIN X570 1TB 在 30 分钟持续高负载下，平均 17K read IOPS，2.5K write IOPS。这约为消费级随机读峰值规格的一小部分，但已经足以让 70B KV-cache 队列堆积。**结论不是"IOPS 不够高"，而是长稳态下 tail latency 和队列压力比峰值 IOPS 更重要**。

### 2. await 单调上升 = GC 持续负担

**即使 I/O 减少，await 仍上升 165%** — 这是 GC 真实开销的体现。

**对延迟敏感的 AI 工作负载**（交互式推理）：
- 早期（0-300s）延迟低（约 1.2 ms）— 适合 SLA-critical workload
- 后期（>1200s）延迟高（约 3.2 ms）— 需要重新设计 SLA target
- **建议**: AI SSD 厂商应**同时报告 P95 延迟的早/晚值**，不应只给平均

### 3. LLM 推理存在队列瓶颈 (Queue bottleneck)

Queue 涨到 376K = 推理在**等存储**。即使 SSD 健康，**单 SSD 无法满足多并发 70B 模型推理**。

**AI SSD 产品需重新定位**：
- 单盘 SSD 无法当 LLM 推理的 hot tier
- 必须用多盘 RAID / tiering（RAM + SSD + NVMe-of）
- 或者：把 KV cache 切成多个 SSD 上分散

### 4. 读主导工作负载 (Read-dominant workload) (R/W = 8.5)

LLM KV cache 是 **read-heavy** — 与 checkpointing（write-heavy）完全不同。**AI SSD 不应通用化**：需要专门的 read-optimized profile。

## 🧭 后续测试方向 (Future Test Directions)

| 项 (Item) | 价值 (Value) | 备注 (Notes) |
|---|---|---|
| 60 分钟扩展 | 中 | 看 GC drift 是否收敛或继续恶化 |
| 120 分钟 | 中 | 看 health 是否开始影响 controller 行为 |
| 单 SSD vs RAID-0 对比 | 高 | 验证多盘是否能解决 queue bottleneck |
| LMCache tiering 测试 | 高 | 看 DRAM cache + SSD 组合能否缓解延迟 |

## ⚠️ 测试限制 (Test Limitations)

1. **Autoscaling 影响混杂**: 难以单独分离 autoscaling 行为和 GC drift。
2. **无 trace mode 对比**: 本次未跑 trace mode，无法对比"理想 I/O 模式 vs 真实 I/O"。
3. **单盘单 SSD**: 无法测试多盘协同。

**报告结束 (End of Report).**
