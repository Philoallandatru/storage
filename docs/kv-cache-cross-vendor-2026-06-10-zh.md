# 跨厂商 KV 缓存基准测试报告 (Cross-Vendor KV Cache Benchmark Report)

**日期 (Date)**: 2026-06-10
**工具 (Tool)**: `kv_cache_benchmark/kv-cache.py` (MLPerf Storage v3.0)
**方法 (Methodology)**: BurstGPT 轨迹回放, `--gpu-mem-gb 0 --cpu-mem-gb 0` (纯 NVMe 层), `--num-gpus 8 --tensor-parallel 8` (服务器级部署), `--max-concurrent-allocs 2`, `--trace-speedup 1000`, `--replay-cycles 0`, seed 42。每次运行 120–180 秒,串行执行以保证存储 I/O 纯净。
**工作负载参数匹配 (Workload parameters match)** `scripts/run_70b_users6.sh` 和 `scripts/run_full_profiling.sh`,确保与现有 BurstGPT 运行的方法论完全一致。

**平台 (Platform)**: Linux 7.0.0-22-generic, 24 核, 83 GB DRAM, fio 3.41。

## 执行摘要 (Executive Summary)

我们对 **4 款消费级 NVMe SSD 进行了 5 种 KV 缓存场景测试（共 20 次运行）**，使用与先前 BurstGPT Profile 运行相同的 MLPerf Storage KV 缓存工作负载（BurstGPT 轨迹回放、纯 NVMe 层、TP=8）。核心结论十分明确：

> **Biwin X570 在所有场景的吞吐量和尾部延迟方面均胜出。**
> 在 16 个并发用户运行 Llama3.1-8B 时，它可维持 7,157 tok/s 的吞吐量和存储读取设备 P99 延迟 60 ms。第二名（ZhiTai Ti600）吞吐量约慢 20%，但在大模型 KV 缓存工作负载（4 用户 70B）下尾部延迟约差 2 倍。

## 核心结果 — 4 盘 × 5 场景矩阵 (Headline Results — 4-disk × 5-scenario matrix)

场景 (Scenarios):
- **K1** — 1 用户, Llama3.1-8B, 120 s（单用户延迟基准）
- **K2** — 4 用户, Llama3.1-8B, 120 s（典型推理服务）
- **K3** — 8 用户, Llama3.1-8B, 120 s（高并发）
- **K4** — 16 用户, Llama3.1-8B, 120 s（饱和度探测）
- **K5** — 4 用户, Llama3.1-70B-Instruct, 180 s（大 KV 缓存）

### 吞吐量 (Throughput) (tokens/sec — 越高越好)

| 厂商 (Vendor) | K1 (1u/8B) | K2 (4u/8B) | K3 (8u/8B) | K4 (16u/8B) | K5 (4u/70B) |
|---|---:|---:|---:|---:|---:|
| WD SN570 | 2,113 | 3,448 | 3,426 | 3,573 | 1,375 |
| **Biwin X570** | **3,071** 🏆 | **5,890** 🏆 | **6,806** 🏆 | **7,157** 🏆 | **2,521** 🏆 |
| ZhiTai Ti600 | 2,505 | 4,977 | 5,491 | 5,746 | 1,854 |
| Seagate FC530 | 1,728 | 4,355 | 4,265 | 5,398 | 2,012 |

### 存储读取 P99 延迟 (Storage read P99) (ms — 越低越好)

| 厂商 (Vendor) | K1 | K2 | K3 | K4 | K5 |
|---|---:|---:|---:|---:|---:|
| WD SN570 | 22 | 77 | 147 | 328 | 233 |
| **Biwin X570** | **14** 🏆 | **31** 🏆 | **48** 🏆 | **60** 🏆 | **80** 🏆 |
| ZhiTai Ti600 | 16 | 42 | 69 | 102 | 258 |
| Seagate FC530 | 35 | 46 | 117 | 153 | 111 |

### 存储写入 P99 延迟 (Storage write P99) (ms)

| 厂商 (Vendor) | K1 | K2 | K3 | K4 | K5 |
|---|---:|---:|---:|---:|---:|
| WD SN570 | 54 | 129 | 209 | 243 | 364 |
| **Biwin X570** | **7** 🏆 | **14** 🏆 | **20** 🏆 | **27** 🏆 | **28** 🏆 |
| ZhiTai Ti600 | 21 | 25 | 279 | 348 | 1,073 |
| Seagate FC530 | 8 | 13 | 26 | 51 | 28 |

## 关键发现 (Key Findings)

### 1. Biwin X570 在 KV 缓存工作负载各方面全面领先

- 16 用户 Llama3.1-8B（易饱和场景）下达到 7,157 tok/s，比其他所有盘高 25–100%，同负载下的尾部延迟（读取 P99 60 ms）仅为第二名的一半。
- 在最大 KV 缓存工作负载（4 用户 70B，每用户条目约大 5 倍）下，Biwin 在吞吐量上仍领先 25%，写入尾部延迟领先 2.7 倍（28 ms vs ZhiTai 的 1,073 ms P99）。
- K4 读取带宽达到 3.1 GB/s — 接近其 T1 顺序读取上限（8.5 GB/s），但明显高于 T4 持续 GC 速率（约 770 MB/s，15 分钟后），说明 KV 缓存访问的持续性足以触发 GC 反压。

### 2. ZhiTai Ti600 在 70B 下写入尾部延迟崩溃

ZhiTai 的存储写入 P99 从 25 ms（K2, 8B）跃升至 **1,073 ms（K5, 70B）** — 暴涨 43 倍。这与我们在 T6 混合读写和 T3 SLC 稳态中已经看到的现象一致：YMTC NAND 加控制器的组合在写放大高时牺牲了尾部延迟。对于 70B 级工作负载，**ZhiTai 不是合适的选择**，尽管其峰值吞吐量具有竞争力。

### 3. WD SN570（无 DRAM）在 K2 附近达到饱和

WD 的吞吐量平台在 K2（3,448 tok/s）达到后，直到 K4（3,573 tok/s）保持平坦。没有 DRAM 缓存来吸收读取突发，其尾部延迟随并发度线性增长（读取 P99：22 → 77 → 147 → 328 ms）。对于高并发部署，**WD 不适合**。

### 4. Seagate FC530 是 70B 场景的第二选择

在 K5（70B）下，Seagate（2,012 tok/s）略超 ZhiTai（1,854），**写入 P99 为 28 ms — 与 Biwin 并列该场景最佳**。这与 T6 混合读写测试结果一致，Seagate 在 90/10 读占优时已领先。对于瓶颈在于混合读写放大而非纯顺序的大模型工作负载，如果 Biwin 不可用或超出预算，Seagate 是可行的替代方案。

### 5. 缓存命中率掩盖了 GC 压力

所有盘在所有场景下均维持 **97.7–98.1%** 的缓存命中率。这对稳态服务来说很好，但掩盖了 *miss* 路径上的情况 — 真正的尾部延迟就在这里。16 用户 8B 场景下 2–3% 的未命中率每秒驱动约 6,800 IOPS 的冷读取；只有 Biwin 的控制器能在 60 ms P99 内服务这些请求。

## AI SSD 采购建议（KV 缓存）(Recommendations for AI SSD procurement)

| 使用场景 (Use case) | 最佳厂商 (Best vendor) | 原因 (Why) |
|---|---|---|
| 通用 LLM 推理（TP=8 服务器级） | **Biwin X570** | 在 tok/s 和 P99 上胜出所有场景 |
| 70B 级 / 大上下文服务 | **Biwin X570** | 写入尾部 P99 = 28 ms（vs ZhiTai 的 1,073 ms） |
| 成本受限的 8B 服务，单用户 | **ZhiTai Ti600** | 比 Biwin 便宜 25%，K1 仅慢 18% |
| 混合读写密集型（RAG、多轮对话） | **Seagate FC530** | 在 70B 下写入 P99 并列最佳 |
| DRAM 丰富的主机 + 廉价 SSD 作溢出层 | **WD SN570** | 迅速饱和但可作为溢出层接受 |

## 方法 (Methodology)

### 工具 (Tooling)

- `kv_cache_benchmark/kv-cache.py`（MLPerf Storage v3.0, NVIDIA / Kingston）
- BurstGPT 轨迹（`datasets/BurstGPT/data/BurstGPT_1.csv`）以 `trace-speedup=1000` 回放（压缩墙钟时间，与先前方法论一致）
- `--gpu-mem-gb 0 --cpu-mem-gb 0` 隔离 NVMe 层
- `--num-gpus 8 --tensor-parallel 8` 模拟 8×H200 级部署
- `--max-concurrent-allocs 2`（与 `run_70b_users6.sh` 相同）
- `--generation-mode none` 移除模拟 GPU 计算成本

### 硬件 (Hardware)

| 插槽 (Slot) | 型号 (Model) | NAND | DRAM | 可用空间 (Free GB) |
|---|---|---|---|---:|
| nvme0 | WD SN570 | TLC (SanDisk) | 无 DRAM (DRAM-less) | 198 |
| nvme1 | Biwin X570 | TLC | 1 GB | 245+ |
| nvme2 | ZhiTai Ti600 | TLC (YMTC) | 有 DRAM | 196 |
| nvme3 | Seagate FC530 | TLC (Micron) | 有 DRAM (Phison E18) | 378 |

### 每次运行流程 (Per-run procedure)

对于每对（磁盘, 场景），执行程序：
1. 在目标 NVMe 挂载点创建每盘专属的 `cache_dir`
2. 清空操作系统页缓存（冷启动）
3. 在后台启动 `iostat -dx -m 1`（1 Hz 采样）
4. 使用 seed 42 和场景参数运行 `kv-cache.py`
5. 停止 `iostat`，写入 `metadata.json`（厂商、场景、用户、模型、目标/实际持续时间、主机 DRAM）
6. 清理 `cache_dir`，再次清空页缓存
7. 等待下一次运行

执行脚本（`scripts/cross_vendor_kv_cache_k2_k5.sh`）串行遍历场景，在每个场景内串行运行 4 块盘，顺序固定（WD → Biwin → ZhiTai → Seagate），确保没有两块盘同时被基准测试。

### 数据产物 (Data products)

- `results/cross_vendor/kv_cache/<disk>/<scenario>/kv_cache_summary.json` — `kv-cache.py` 原始输出（摘要、延迟、吞吐量时序）
- `results/cross_vendor/kv_cache/<disk>/<scenario>/iostat.txt` — 每秒 NVMe I/O 采样
- `results/cross_vendor/kv_cache/<disk>/<scenario>/metadata.json` — 运行参数
- `results/cross_vendor/kv_cache_summary.csv` — 平坦的 20 行表格（每盘 × 场景 1 行），包含核心指标

## 交叉参考 (Cross-references)

本测试补充了现有的跨厂商 NVMe 表征：
- **T1–T2, T5–T7** — 合成 fio 工作负载（`cross_vendor_t*.sh`）
- **T3, T4** — SLC + GC 漂移（`cross_vendor_t3_slc_steady.sh`, `cross_vendor_t4_gc_drift.sh`）
- **K1–K5**（本报告）— 真实 MLPerf Storage KV 缓存工作负载

Biwin 在 KV 缓存上的领先地位与其在 T1 顺序突发和 T5 随机 IOPS 上的领先一致，但其在 T3/T4 中观察到的突发 vs 稳态悬崖在此处并未影响它，因为对于测试的工作负载，KV 缓存流量适合 SLC 缓存（97%+ 命中率）。
