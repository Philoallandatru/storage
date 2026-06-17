# KV 缓存跨厂商 NVMe SSD — 最终选择报告 (KV Cache Cross-Vendor NVMe SSD — Final Selection Report)
**日期 (Date):** 2026-06-10
**范围 (Scope):** 4 款消费级 NVMe SSD × 4 种 KV 缓存场景 × 1800 秒长期稳态
**受众 (Audience):** AI 基础设施团队 — LLM 推理服务节点的 NVMe SSD 采购

本报告整合了 K5、K4、K4-GC-drift（20 分钟）和 K4-30-min-drift 结果及 IO 模式分析，形成一份决策文档。

---

## TL;DR — 一段话建议 (One-paragraph recommendation)

**30 分钟时，Biwin X570 和 Seagate FC530 在功能上等效（1.57 vs 1.54 GB/s — 在运行间噪音范围内）。** 两者在 30 分钟时均提供约 1.55 GB/s 的可用读取带宽，但两者每约 10 分钟会出现持续 5 分钟的 GC 暂停事件，将带宽降至约 0.2 GB/s。Seagate 的暂停更浅，其写入尾部延迟持续更低（30 分钟时 213 ms vs 227 ms）。对于实际部署中 30 分钟以上的会话，根据供应链和成本选择即可 — 两款盘均可接受。短会话（<5 分钟）显然更倾向 Biwin 以获得峰值带宽；混合 checkpoint+推理则明显倾向 Seagate 以获得更好的写入尾部延迟。**ZhiTai Ti600 和 WD SN570 在任何场景下均不推荐用于 KV 缓存工作负载。**

---

## 测试矩阵 (Test matrix)

| 测试 (Test) | 模型 (Model) | 用户数 (Users) | 时长 (Duration) | 层 (Tier) | 目标 (Goal) |
|---|---|---|---:|---:|---|---|
| K5 | LLaMA-3.1-70B | 4 | 180 s | force NVMe | 单请求大条目延迟 |
| K4 | LLaMA-3.1-8B | 16 | 120 s | force NVMe | 高并发小条目吞吐量 |
| K4 GC drift | LLaMA-3.1-8B | 16 | 1200 s | force NVMe | 稳态 GC 悬崖检测 |
| K4 30-min drift | LLaMA-3.1-8B | 16 | 1800 s (Biwin/Seagate) / 900 s (ZhiTai/WD) | force NVMe | 20 分钟后的持续退化 |

所有测试使用 BurstGPT 轨迹回放，`--trace-speedup 1000`，seed=42，相同磁盘缓存目录。

---

## 核心结果 (Headline results)

### 读取带宽 (Read bandwidth): 3 场景 × 4 磁盘

![读取带宽对比 (Read bandwidth comparison)](assets/charts/01_k4_k5_bw_compare.png)

| 磁盘 (Disk) | K5 突发 (70B) | K4 突发 (8B×16) | **K4 GC 漂移 (8B×16, 20 分钟)** |
|---|---:|---:|---:|
| Biwin X570 | 2.77 | **3.14** | 1.92 |
| Seagate FC530 | 2.09 | 2.34 | **1.91** |
| ZhiTai Ti600 | 1.93 | 2.46 | 1.01 |
| WD SN570 | 1.49 | 1.55 | 1.25 |

**突发和稳态之间的排名发生反转。** Biwin 和 Seagate 在 20 分钟后收敛至约 1.9 GB/s；ZhiTai 降至 1.0 GB/s。

### 多指标排名 (Multi-metric ranking) (K4 GC drift)

![多指标排名热力图 (Multi-metric ranking heatmap)](assets/charts/05_summary_ranking.png)

绿色 = 最佳，红色 = 最差。Seagate 在写入 P99 和读取 P99 上胜出；Biwin 在读取带宽和服务条目数上胜出；ZhiTai 和 WD 除低延迟随机读取 P50 外在所有指标上落败。

---

## GC 悬崖时间 (GC cliff timing)

![每盘 GC 悬崖检测 (GC cliff detection per disk)](assets/charts/03_cliff_detection.png)

| 磁盘 (Disk) | 悬崖时间 (Cliff time) | 下降幅度 (Drop) |
|---:|---:|---:|
| Biwin X570 | **2.9 分钟** | −40.6% |
| ZhiTai Ti600 | 5.6 分钟 | **−77.8%** |
| WD SN570 | 7.8 分钟 | −40.6% |
| **Seagate FC530** | **8.1 分钟** | **−32.0%** |

Seagate 的悬崖出现最晚且下降最浅。Biwin 的悬崖出现最早 — 其 SLC 缓存在 3 分钟标记处耗尽。

---

## IO 模式特征分析 (IO pattern characterization)

KV 缓存卸载是**纯随机 IO**，而非顺序流：

- **读取请求大小: ~125 kB**（约 30 × 4K 页）
- **写入请求大小: ~115 kB**
- **%rrqm = 0%** — 所有四个磁盘的内核从未合并相邻读取
- **%wrqm ≈ 0.1%** — 写入也基本上是随机的

这是 **"稀疏大块随机" IO** — 对分散 LBA 的大请求。该模式由应用程序锁定（由 LLaMA KV 条目大小决定），SSD 厂商无法缩小。

### IO 箱线图 (IO boxplots)

![IO 模式箱线图 (IO pattern boxplots)](assets/charts/04_io_pattern_boxplots.png)

左侧两个面板：每块盘的读/写请求大小约为 125/115 kB（LLaMA-3.1-8B KV 条目大小的特征）。
右侧两个面板：Biwin 在读取服务时间上最快（r_await 中位数 0.38 ms）。**Seagate 在写入服务时间上显著优于其他所有盘** — 对数刻度的 w_await 面板显示 Seagate 约 7 ms vs Biwin 约 14 ms vs ZhiTai 约 120 ms vs WD 约 60 ms。

### 写入服务时间漂移 (Write service time drift)

![写入服务时间漂移 (Write service time drift)](assets/charts/06_write_p99_drift.png)

**ZhiTai 和 WD 在几分钟内进入持续的 100 ms+ 写入延迟**，Biwin 攀升至 10–30 ms，Seagate 保持在约 7 ms。

---

## 每盘评估 (Per-disk verdict)

### 🥇 Seagate FC530 — 推荐用于持续服务
- 最大有效 SLC 缓存（悬崖在 8.1 分钟）。
- 所有指标上最佳的写入服务时间（20 分钟时 w_await p99 为 24 ms，30 分钟时为 213 ms）。
- 读取带宽与 Biwin 收敛于 1.91 GB/s（20 分钟）→ 1.54 GB/s（30 分钟）— *仍然强劲*。
- 长时间运行时 GC 暂停比 Biwin 更浅。
- Phison E18 + 高端 NAND + DRAM 在随机 IO 下表现出色。

### 🥈 Biwin X570 — 推荐用于纯突发服务
- 最佳峰值带宽（K4 突发 3.14 GB/s，30 秒悬崖峰值 4.9 GB/s）。
- 最佳读取 r_await（0.38 ms）。
- *但是：* SLC 缓存在 2.9 分钟时耗尽 — 不适用于超过 5 分钟的会话。
- 30 分钟时，带宽已退化至 1.57 GB/s — 与 Seagate 在噪音范围内相当。
- SLC 耗尽后每 10 分钟出现约 5 分钟的带宽归零事件（类似 Seagate 但更深）。

### 🥉 ZhiTai Ti600 — 不推荐
- K4 GC 漂移带宽最低（20 分钟时 1.01 GB/s）。
- 写入 P99 最差（20 分钟时 725 ms，30 分钟时 607 ms）— 每次驱逐都是数百毫秒的暂停。
- YMTC NAND 无法在生产速率下维持随机写入。

### 4️⃣ WD SN570 — 不推荐
- 无 DRAM 架构从一开始就限制吞吐量（K4 GC 漂移 1.25 GB/s）。
- 20 分钟时写入 P99 为 480 ms — 与 ZhiTai 相当。
- 避免用于任何 KV 缓存卸载工作负载。

---

## 最终选择矩阵 (Final selection matrix)

| 工作负载特征 (Workload profile) | 推荐磁盘 (Recommended disk) | 备用 (Backup) | 避免 (Avoid) |
|---|---|---|---|
| 交互式推理（< 3 分钟） | Biwin X570 | Seagate FC530 | ZhiTai, WD |
| 持续批量推理（> 5 分钟） | **Seagate FC530** | Biwin X570 | ZhiTai, WD |
| 混合推理 + 定期 checkpointing | **Seagate FC530** | Biwin X570 | ZhiTai, WD |
| 混合服务（突发 + 长会话） | **Seagate FC530** | — | ZhiTai, WD |

---

## 更多阅读 (Where to read more)

| 文档 (Document) | 覆盖内容 (What it covers) |
|---|---|
| `kv-cache-4disk-K5-headline-2026-06-10.md` | K5（70B, 180 s）详细结果 |
| `kv-cache-4disk-K4-headline-2026-06-10.md` | K4（8B×16, 120 s）详细结果 |
| `kv-cache-4disk-K4-gc-drift-2026-06-10.md` | K4 GC 漂移（1200 s）详细结果 |
| `kv-cache-4disk-K4-30min-drift-2026-06-10.md` | K4 30 分钟漂移（1800 s / 900 s）|
| `kv-cache-io-pattern-analysis-2026-06-10.md` | 使用 iostat 的 IO 模式分析 |

---

## 原始数据 (Raw data)

```
results/cross_vendor/kv_cache_k5_only/      — K5 (180 s)
results/cross_vendor/kv_cache_k4_only/      — K4 (120 s)
results/cross_vendor/kv_cache_k4_gc_drift/  — K4 GC 漂移 (1200 s)
results/cross_vendor/kv_cache_k4_30min_drift/ — K4 30 分钟漂移 (1800 s / 900 s)
docs/assets/charts/                          — 本报告中使用的 8 张 matplotlib 图表
docs/assets/kv_cache_gc_drift_bw_trend.txt   — 带宽趋势的 ASCII 备份
scripts/render_kv_cache_charts.py            — 重新生成图表 1–6
scripts/render_30min_charts.py               — 重新生成图表 7–8
scripts/analyze_kv_cache_iostat.py           — 重新生成 IO 分析 JSON
```
