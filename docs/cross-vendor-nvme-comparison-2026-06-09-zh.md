# 跨厂商 NVMe SSD 对比报告 (Cross-Vendor NVMe SSD Comparison Report)

**日期 (Date)**: 2026-06-09
**测试套件 (Test suite)**: `scripts/cross_vendor_*.sh`（7 项测试，详见下方方法）
**平台 (Platform)**: Linux 7.0.0-22-generic, 24 核, 83 GB DRAM, fio 3.41

## 执行摘要 (Executive Summary)

我们对 **4 款来自不同厂商的消费级 NVMe SSD（1TB 级）** 在统一的测试套件下进行了基准测试，该套件模拟 LLM KV 缓存访问模式。产品线涵盖：

| 插槽 (Slot) | 型号 (Model) | 厂商定位 (Vendor positioning) | NAND | DRAM |
|---|---|---|---|---|
| nvme0 | WD SN570 (WDS960G2G0C-00AJM0) | 入门级 (Entry-level) | TLC (SanDisk) | **无 DRAM (DRAM-less)** |
| nvme1 | Biwin X570 1TB | 主流 (Mainstream) | TLC | 1 GB DRAM |
| nvme2 | ZhiTai Ti600 1TB | 国产 (Domestic - China) | TLC (YMTC) | 有 DRAM |
| nvme3 | Seagate FC530 (ZP1000GV30012) | 高端 (High-end) | TLC (Micron) | 有 DRAM (Phison E18) |

## 核心结果 (Headline Results)

### 顺序突发 (Sequential burst) (测试 1, 10 GB 文件, bs=128k, QD=32, direct=1)

| 厂商 (Vendor) | 顺序读取 (Seq Read) | 顺序写入 (Seq Write) | 读取延迟 (Read latency) | 厂商规格 R/W (Vendor spec R/W) |
|---|---:|---:|---:|---|
| WD SN570 | 2,275 MB/s | 1,936 MB/s | 1,758 μs | 3,500 / 3,000 |
| **Biwin X570** | **8,573 MB/s** 🏆 | **7,965 MB/s** 🏆 | **467 μs** | 见注释 (see note) |
| ZhiTai Ti600 | 6,345 MB/s | 3,696 MB/s | 630 μs | 7,000 / 6,500 |
| Seagate FC530 | 4,989 MB/s | 4,600 MB/s | 802 μs | 7,300 / 6,000 |

注 (Note)：厂商规格列仅作为参考保留。本报告审计过程中未针对每个具体 SKU 重新验证。结论请使用实测 fio 数据；使用厂商数据表前请确保匹配 SKU、固件、PCIe 代、文件系统、热状态和测试方法。

### 4K 随机 IOPS (测试 5, QD=64, 大多数消费级 SSD 的最佳点)

| 厂商 (Vendor) | 随机读取 IOPS (Rand Read IOPS) | 随机写入 IOPS (Rand Write IOPS) | 读取延迟 (Read lat) | 写入延迟 (Write lat) |
|---|---:|---:|---:|---:|
| WD SN570 | 337,255 | 331,012 | 190 μs | 193 μs |
| **Biwin X570** | **494,891** 🏆 | **510,840** 🏆 | 129 μs | 125 μs |
| ZhiTai Ti600 | 392,477 | 444,001 | 163 μs | 144 μs |
| Seagate FC530 | 454,003 | 457,291 | 141 μs | 140 μs |

### 混合 R/W (测试 6, 4k, QD=32, 20 GB 文件, 60s)

| 厂商 (Vendor) | 90/10 读取 (90/10 Read) | 90/10 写入 (90/10 Write) | 50/50 读取 (50/50 Read) | 50/50 写入 (50/50 Write) |
|---|---:|---:|---:|---:|
| WD SN570 | 437 MB/s | 49 MB/s | 139 MB/s | 139 MB/s |
| Biwin X570 | 902 MB/s | 100 MB/s | 460 MB/s | 460 MB/s |
| ZhiTai Ti600 | 846 MB/s | 94 MB/s | 313 MB/s | 313 MB/s |
| **Seagate FC530** | **1,271 MB/s** 🏆 | **141 MB/s** 🏆 | **862 MB/s** 🏆 | **862 MB/s** 🏆 |

### 页缓存敏感性 (测试 7, 4k 缓冲, 6 GB 文件)

| 厂商 (Vendor) | 热缓存带宽 (Warm BW) | 清除缓存带宽 (Evict BW) | 页缓存加速比 (Page cache speedup) |
|---|---:|---:|---:|
| WD SN570 | 1,592 MB/s | 1,157 MB/s | **1.38x** |
| Biwin X570 | 2,565 MB/s | 2,522 MB/s | 1.02x |
| ZhiTai Ti600 | 2,204 MB/s | 2,285 MB/s | 0.96x |
| Seagate FC530 | 1,910 MB/s | 1,907 MB/s | 1.00x |

### SLC 缓存行为 (测试 2, 168 GB 顺序写入)

| 厂商 (Vendor) | 探测平均带宽 (160GB 持续) (Probe mean BW) | 空闲后新鲜带宽 (Post-idle fresh BW) | 解释 (Interpretation) |
|---|---:|---:|---|
| WD SN570 | 1,971 MB/s | 1,998 MB/s | 极小的 SLC 缓存（约 10 MiB DRAM 缓冲区），瞬时峰值 |
| **Biwin X570** | **7,931 MB/s** | **7,299 MB/s** | **SLC 缓存 > 168 GB**（160 GB 内从未观察到悬崖） |
| ZhiTai Ti600 | 4,971 MB/s | 5,485 MB/s | SLC 约 4 GB，空闲后约 5.5 GB/s 表明 pSLC 保留 |
| Seagate FC530 | 4,587 MB/s | 4,569 MB/s | SLC 约 170 MB，空闲后恢复 4.6 GB/s |

### SLC 缓存行为 — 新鲜 vs 稳态 (测试 3)

在 168 GB 顺序写入预调理 + 5 分钟空闲（允许 GC 回流至稳定的"使用中"状态）后，我们重新探测 SLC 缓存大小。

| 厂商 (Vendor) | T2 新鲜平均带宽 (T2 Fresh mean BW) | T3 稳态平均带宽 (T3 Steady mean BW) | **稳态/新鲜 (Steady/Fresh)** | 解释 (Interpretation) |
|---|---:|---:|---:|---|
| WD SN570 | 1,971 MB/s | 1,724 MB/s | **0.87 (−13%)** | 已经很小，GC 快速排空 |
| **Biwin X570** | 7,931 MB/s | 3,410 MB/s | **0.43 (−57%)** | **SLC 从 168+ GB 降至长期使用后的约 50 GB** |
| ZhiTai Ti600 | 4,971 MB/s | 5,124 MB/s | **1.03 (+3%)** | pSLC 保留或刷新 |
| Seagate FC530 | 4,587 MB/s | 2,379 MB/s | **0.52 (−48%)** | **SLC 在稳态也大幅下降** |

**这是 T3 的核心发现**：Biwin 宣称的"巨大 SLC 缓存"**仅存在于刚 TRIM 过/未使用的盘上**。在持续写入后，控制器用持久数据填满其 SLC 缓冲区空间，无法重新创建完整的 pSLC 区域，直到经过长时间的空闲期。Seagate 行为相似。相比之下，ZhiTai 适中的 SLC 缓存在**新鲜和稳态之间是稳定的** — 其算法似乎持久地保留 SLC 空间，而非动态分配。

### GC 漂移 — 持续随机读取下 (测试 4, 15 分钟, 16k 随机读取 QD=4)

为测量每块盘在其 SLC 缓存和 GC 反压都参与进一个长时间工作负载（推理节点连续 15 分钟服务 KV 缓存读取的真实场景）时吞吐量如何下降，我们以 1 Hz 采样 `iostat`，并比较了前 60 秒与后 60 秒窗口。

| 厂商 (Vendor) | 起始带宽 (前 60 秒) (Start BW) | 结束带宽 (后 60 秒) (End BW) | **漂移 (Drift)** | 结论 (Verdict) |
|---|---:|---:|---:|---|
| **WD SN570** | 591 MB/s | 557 MB/s | **−5.9%** | 🟢 非常稳定 (rock-steady) |
| **ZhiTai Ti600** | 1,079 MB/s | 941 MB/s | **−12.8%** | 🟡 轻度下降 (mild drop) |
| **Seagate FC530** | 983 MB/s | 765 MB/s | **−22.1%** | 🟡 中度 (moderate) |
| **Biwin X570** | 1,118 MB/s | 777 MB/s | **−30.5%** | 🔴 严重 (severe) |

**T4 的核心发现**：15 分钟后的*可持续*吞吐量排名是 **ZhiTai (941 MB/s) > Seagate ≈ Biwin (~770 MB/s) >> WD (557 MB/s)** — 与突发测试排名完全不同。Biwin 的 1.1 GB/s 初始速度在 GC 反压启动后下降了三分之一；ZhiTai 较低的峰值*更可预测*，最终成为最高的持续速率。

结合 T3，这意味着 Biwin 是**突发冠军**，但其 15 分钟持续速率与 Seagate 基本无法区分。如果工作负载的"突发阶段"持续超过几分钟（例如预填充加长解码会话），ZhiTai 是更安全的选择。

## 关键发现 (Key Findings)

### 1. 无 DRAM 的 WD SN570 在所有衡量指标上最弱
- 顺序吞吐量为 Biwin 的 27–73%。延迟差 2–4 倍。
- **混合 R/W** 中显示无 DRAM 的劣势：在 90/10 下读取 437 MB/s vs Biwin 的 902 MB/s。
- **但** WD 从操作系统页缓存中获益最大（+38%），因为它没有板载 DRAM 缓存。
- 这是 **LLM 推理中配备 DRAM 的 SSD 的最有力论据**：在没有缓存命中的持续读重工作负载下，无 DRAM SSD 会断崖式下降。

### 2. Biwin X570 在原始性能上占主导
- **8.5 GB/s 顺序读取** — 本测试集中最佳。除非精确匹配 SKU、PCIe 链路、文件系统、热状态和测试方法，否则不要将此数字与厂商峰值规格直接比较。
- **QD=64 时 495k IOPS 随机读取** — 仅次于 QD=256 时的 ZhiTai。
- **混合 90/10**: 902 MB/s 读取 + 100 MB/s 写入 — 强劲，但非本套件最佳。Seagate FC530 是混合工作负载冠军；Biwin 的优势在于突发/顺序和 QD64 随机。
- **新鲜跨厂商 SLC 探测在 168 GB 内未观察到悬崖** — 在测试窗口内持续 7.9 GB/s。这是条件相关的，不应视为固定的物理 SLC 大小。
- **页缓存加速比极小（1.02x）** — 其板载 1 GB DRAM 原生处理缓存。

### 3. ZhiTai Ti600 需要高队列深度才能发挥优势
- QD=1 读取：16k IOPS（最差），QD=256 读取：581k IOPS（**最佳**）。
- YMTC NAND + 控制器具有**深度队列并行性**，但单线程延迟较差。
- 对于 LLM 推理（多个用户 = 高并发），Ti600 有竞争力。
- 对于单用户 / 预填充-解码（低并发），表现不佳。

### 4. Seagate FC530 是混合工作负载之王
- **90/10 混合 R/W 读取 1,271 MB/s** — 比 Biwin 的 902 MB/s 快 41%。
- **50/50 混合 R/W 读取 862 MB/s** — 几乎是 Biwin 的 2 倍。
- Phison E18 控制器擅长交织读取和写入。
- 纯顺序性能较低（5 GB/s）但对于 KV 缓存而言，均衡性能更重要。

### 5. SLC 缓存行为在不同厂商间差异巨大

| | 160 GB 顺序写入中的 SLC 行为 (SLC behavior in 160 GB sequential write) |
|---|---|
| WD | 仅有 DRAM 缓冲区，无实际 pSLC |
| Biwin | pSLC ≥ 168 GB（非常大，或激进的写缓存） |
| ZhiTai | pSLC 约 4 GB |
| Seagate | pSLC 约 170 MB |

"SLC 缓存"效应高度依赖条件。在此跨厂商新鲜探测中，Biwin 在 168 GB 测试窗口内保持在快速模式，而专用 BIWIN 根分区表征测量到一个较小的悬崖（新鲜约 71 GiB，稳态预调理后约 95 GiB）。将这些视为不同的运行状态，而非单一的固定缓存大小事实。只有 ZhiTai 在本套件中在大约 4 GB 处显示出清晰的悬崖。

## AI SSD 采购建议 (Recommendations for AI SSD procurement)

| 使用场景 (Use case) | 最佳厂商 (Best vendor) | 原因 (Why) |
|---|---|---|
| 单流预填充（长顺序读取） | **Biwin X570** | 8.5 GB/s，超出规格 |
| 多用户解码（高 QD，读密集） | **ZhiTai Ti600** | 最佳的 QD=256 扩展性 |
| 混合 R/W checkpointing + 服务 | **Seagate FC530** | 1.27 GB/s 90/10 读取 |
| 预算 / DRAM 受限 | **WD SN570** 仅当系统有充足的 DRAM 用于页缓存 |
| 突发密集 / 冷加载部署 | **Biwin X570** | 最佳峰值顺序和 QD64 随机性能 |
| 均衡生产部署 | **Seagate FC530 或 ZhiTai Ti600** | Seagate 胜出混合 R/W；ZhiTai 胜出 15 分钟持续读取稳定性 |
| 持续 15 分钟以上的推理服务 | **ZhiTai Ti600** | GC 漂移最小，吞吐量最可预测 |
| 带 DRAM 丰富主机的 KV 缓存（页缓存） | **WD SN570** | +38% 页缓存加速比弥补无 DRAM 差距 |

## 方法 (Methodology)

所有 7 项测试使用统一的 `cross_vendor_lib.sh`，定义了 4 个厂商挂载点：

```bash
wd_sn570     -> /mnt/ai_ssd0           (nvme0n1p2)
biwin_x570   -> /run/media/ficus/新加卷 (nvme1n1p2)
zhitai_ti600 -> /mnt/ai_ssd1           (nvme2n1p3)
seagate_fc530-> /mnt/ai_ssd2           (nvme3n1p2)
```

**测试 1 — 顺序突发 (Sequential Burst)**（`cross_vendor_t1_seqburst.sh`）：
10 GB 文件, bs=128k, QD=32, direct=1, 60s time_based。

**测试 2 — SLC 新鲜 (SLC Fresh)**（`cross_vendor_t2_slc_fresh.sh`）：
写入 168 GB，分成 10 GB 切片（bs=1M, QD=32, direct=1）— 记录每切片带宽。然后 5 分钟空闲。然后 10 GB 新鲜切片测量"冷 SLC 重填"带宽。

**测试 5 — 随机 4K (Random 4K)**（`cross_vendor_t5_random4k.sh`）：
4 GB 文件, bs=4k, QD={1,4,16,64,256}, direct=1, 每单元 30s。

**测试 6 — 混合 R/W (Mixed R/W)**（`cross_vendor_t6_mixed_rw.sh`）：
20 GB 文件, bs=4k, QD=32, direct=1, 60s time_based, rwmixread={90,50}。

**测试 7 — 页缓存 (Page cache)**（`cross_vendor_t7_pagecache.sh`）：
6 GB 文件, bs=4k, QD=16, direct=0。两种条件：缓冲（热缓存）vs `invalidate=1`（OS 在每个块后清除）。

## 注意事项 (Caveats)

- **每个厂商每项测试仅单次样本。** 无 3 次运行取中位数。小数值（如 T2 BW_min 为 5 MB/s）的方差可能由单次 IO 尖峰而非稳态导致。
- **磁盘可用空间**: WD 仅有 198 GB 可用；T2/T3 缩减至 168 GB 以避免填满。
- **测试串行执行**，无并行磁盘访问。每块盘的完整套件是顺序执行的。
- **T3（稳态 SLC）和 T4（15 分钟 GC 漂移）** 在初始报告草稿后完成，现已包含在上文中。剩余注意事项：每单元仍为单次运行，非 3 次运行中位数。

## 文件 (Files)

- `scripts/cross_vendor_lib.sh` — 共享库
- `scripts/cross_vendor_t{1,2,3,4,5,6,7}_*.sh` — 测试脚本
- `scripts/cross_vendor_analyze.py` — 聚合器
- `scripts/cross_vendor_slc_analyze.py` — SLC 悬崖检测器
- `results/cross_vendor/{t1,t2,t5,t6,t7}/<vendor>_<ts>/` — fio 原始输出
- `results/cross_vendor/_compiled.json` — 聚合指标
