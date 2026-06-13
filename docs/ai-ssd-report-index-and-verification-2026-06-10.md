# AI SSD KV Cache 报告索引与结论核验

日期：2026-06-10

本文用于整理当前仓库内 AI SSD / KV Cache 相关报告，并说明哪些结论已经通过本地结果文件复核，哪些报告属于历史中间态，哪些地方已经修正。

## 核验范围

本次核验覆盖：

| 类型 | 路径 |
|---|---|
| KV Cache benchmark JSON | `results/kvcache-profile/*.json` |
| fio sweep CSV/JSON | `results/kvcache-profile/fio_sweep*`, `results/cross_vendor/**` |
| SSD characterization | `results/ssd-characterization/**` |
| 报告文档 | `docs/*kvcache*`, `docs/*ssd*`, `docs/cross-vendor-nvme-comparison-2026-06-09.md` |

未上传也不应上传：

| 类型 | 原因 |
|---|---|
| `results/` 原始数据 | 大量实验产物，Git 中应忽略 |
| 原始 bpftrace/iostat/pidstat 日志 | 可很大，且可由摘要复现关键结论 |
| 数据集 | 体积和授权风险 |
| `uv.lock` 当前本地变化 | 与报告核验无关 |

## 当前权威报告入口

| 优先级 | 报告 | 状态 | 用途 |
|---|---|---|---|
| 1 | `docs/ai-ssd-kvcache-integrated-prestudy-report-2026-06-13.md` | 新增 | 6月13日整合大报告，作为当前主入口 |
| 2 | `docs/ai-ssd-kvcache-complete-archive-report-2026-06-13.md` | 新增 | 完整实验归档，覆盖主线和支线测试 |
| 3 | `docs/kvcache-ai-ssd-product-prestudy-complete-2026-06-08.md` | 已修正 | KV Cache + AI SSD 产品预研总入口 |
| 4 | `docs/kvcache-saturation-points-2026-06-08.md` | 已修正 | 70B users12 / 8B users32 饱和边界 |
| 5 | `docs/kvcache-long-steady-state-2026-06-09.md` | 已修正措辞 | 30 分钟长稳态和 GC drift |
| 6 | `docs/cross-vendor-nvme-comparison-2026-06-09.md` | 已修正 caveat | 四盘横向对比 |
| 7 | `docs/biwin-x570-ssd-characterization-2026-06-08.md` | 已核验 | BIWIN X570 Gen5/TLC-like/SLC cache 基础判断 |
| 8 | `docs/biwin-x570-slc-steady-state-vs-fresh-2026-06-09.md` | 可用，需单次样本 caveat | BIWIN fresh vs steady SLC cache |
| 9 | `docs/biwin-x570-slc-mixed-rw-2026-06-09.md` | 可用，需单次样本 caveat | mixed R/W 下 SLC cache 价值 |
| 10 | `docs/kvcache-pagecache-sensitivity-2026-06-09.md` | 可用，需 order-effect caveat | DRAM page cache 敏感性 |
| 11 | `docs/ai-ssd-multidisk-validation-plan-2026-06-10.md` | 新增 | 多盘对比设计与 AI SSD 产品验证计划 |

历史报告：

| 报告 | 状态 |
|---|---|
| `docs/kvcache-ai-ssd-final-summary-2026-06-08.md` | 历史中间版，未包含 6月9日长稳态/跨盘/页面缓存等最新结果 |
| `docs/kvcache-ai-ssd-prestudy-2026-06-08.md` | 早期预研版 |
| `docs/kvcache-io-profiling-visual-analysis-2026-06-08.md` | 图表版，适合解释 profiling 方法，但不是最新总判断 |

## 已核验和修正的关键点

### 1. Saturation sweep 数字修正

源文件：

| Run | JSON |
|---|---|
| 70B users12 hwio | `results/kvcache-profile/test_burstgpt_70b_tp8_cpu0g_users12_20260608_214710_hwio.json` |
| 8B users32 hwio | `results/kvcache-profile/test_burstgpt_8b_tp8_cpu0g_users32_20260608_215751_hwio.json` |

复核后的关键值：

| 指标 | 70B users12 | 8B users32 |
|---|---:|---:|
| Requests | 3363 | 7726 |
| Request/s | 11.21 | 25.75 |
| Storage I/O P95 | 2295.21ms | 661.39ms |
| Read Device P95 | 128.26ms | 43.86ms |
| Write Device P95 | 154.63ms | 112.67ms |
| E2E P95 | 141.31s | 129.36s |
| E2E P99 | 148.13s | 131.21s |
| Cache hit | 97.69% | 97.75% |
| Storage read | 911.89GiB | 823.89GiB |
| Storage write | 77.55GiB | 71.77GiB |
| Storage health | PASS | PASS |

修正说明：

1. 8B users32 不能再写成 “SLA 100% PASS”。它只是 device-level 仍轻，service-level 已受 autoscaling/排队影响。
2. 70B users12 的 E2E P95/P99 使用 JSON 复核值：141.31s / 148.13s。
3. 70B users12 的 autoscaler final users 是 109，不是 500。
4. 8B users32 的 saturation level 最高约 0.49，接近 0.5 阈值但未超过。

当前结论：

| 层级 | 结论 |
|---|---|
| Device-level | 70B users12 明显重；8B users32 仍相对轻 |
| Service-level | 两者都因 autoscaling/队列导致 E2E/QoS 不健康 |
| 产品判断 | 70B users8 到 users12 之间是当前设备的关键边界；8B 需要单独建模 device boundary 和 service boundary |

### 2. Long steady-state 文档措辞修正

源文件：

`results/kvcache-profile/test_long_steady_state_30min_20260609_103815.json`

复核值：

| 指标 | 值 |
|---|---:|
| Requests | 24285 |
| Request/s | 13.49 |
| Storage I/O P95 | 1656.59ms |
| E2E P95 | 838.05s |
| Read Device P95 | 160.75ms |
| Write Device P95 | 148.22ms |
| Cache hit | 95.93% |
| Storage read | 3678.84GiB |
| Storage write | 439.33GiB |
| Storage health | PASS |

修正说明：

原文里 “17K read IOPS 超过 spec 98K 的 17%” 表述不严谨，已改为：17K read IOPS 约为消费级峰值规格的一小部分，但已经足以让 70B KV-cache 队列堆积。产品重点应看 tail latency 和队列压力，而不是峰值 IOPS。

### 3. Cross-vendor 报告修正

源文件：

`results/cross_vendor/_compiled.json`  
`results/cross_vendor/t4_gc_drift_summary.json`

复核确认：

| 项 | 状态 |
|---|---|
| T1 sequential burst | 主要数字与 `_compiled.json` 一致 |
| T5 random 4K | 主要数字与 `_compiled.json` 一致 |
| T6 mixed R/W | 主要数字与 `_compiled.json` 一致 |
| T7 page cache | 主要数字与 `_compiled.json` 一致 |
| T4 GC drift | 主要数字与 `t4_gc_drift_summary.json` 一致 |

已修正：

1. 原 caveat 写 T3/T4 未完成，但正文已经包含 T3/T4；现已改为“已完成，但仍是 single run”。
2. vendor spec 列不再作为结论依据，仅保留作上下文；跨盘结论以 fio 实测值为准。
3. BIWIN SLC cache 结论加了条件限定：cross-vendor fresh probe 未在 168GiB 内观察到 cliff，但 dedicated BIWIN root partition 测得约 71GiB fresh / 95GiB steady。两者是不同测试状态，不应合并成固定 SLC cache size。

当前跨盘结论：

| 场景 | 最优/更合适 |
|---|---|
| Sequential burst | BIWIN X570 |
| Random 4K QD64 | BIWIN X570 |
| Mixed R/W 90/10 或 50/50 | Seagate FC530 |
| 15 分钟持续读 GC drift | ZhiTai Ti600 更稳定 |
| DRAM-less 低成本盘 | WD SN570 依赖 host page cache，长期 AI serving 不推荐作主力 |

### 4. BIWIN X570 盘体判断

源文件：

`results/ssd-characterization/ssd_slc_biwin_x570_200g_20260608_231549/ssd_characterization_report.md`

复核值：

| 指标 | 值 |
|---|---:|
| PCIe link | Gen5 x4 (`32.0 GT/s`, width 4) |
| Total write | 200GiB |
| Average write | 2014.20MiB/s |
| Cache-in speed | 5078.54MiB/s |
| Post-cache speed | 1668.83MiB/s |
| Steady tail speed | 1603.10MiB/s |
| Estimated SLC cache | ~71.36GiB |
| Media tendency | strong TLC-like |

结论：

BIWIN X570 1TB 当前链路为 PCIe Gen5 x4，写入行为强 TLC-like。测试行为不能物理证明 NAND 类型，但结合公开规格和 post-cache 速度，不符合典型低端 QLC 的出缓存崩塌特征。

## 当前产品级结论

1. AI SSD 预研必须同时区分 device-level 和 service-level。Device P95 PASS 不代表 serving SLA PASS。
2. KV Cache 对 SSD 的核心压力不是单条 4K latency，而是 KV object tail、队列堆积、mixed R/W、GC drift。
3. 70B TP8 CPU0 BurstGPT 是比 8B 更有价值的产品边界 workload。
4. BIWIN X570 是强 burst 盘，但 15 分钟持续读下 drift 明显；ZhiTai 峰值不一定最高，但持续性更好。
5. mixed R/W 场景下 SLC cache burst 价值明显下降，AI SSD 产品不能只宣传顺序写入 SLC 峰值。
6. 后续对候选 AI SSD 应固定报告：fresh/steady SLC、mixed R/W、KV object P95/P99、long steady GC drift、page cache sensitivity、70B service boundary。

## 推荐后续报告结构

未来新增测试应按以下层次写，避免报告互相冲突：

| 层 | 内容 |
|---|---|
| Hardware characterization | PCIe generation, NAND tendency, SLC cache, post-cache, steady speed |
| Synthetic SSD tests | fio sequential/random/mixed, fresh vs preconditioned |
| KV object tests | benchmark JSON: device/host/total P95/P99, tier bytes |
| Full profiling | io trace, bpftrace, iostat, pidstat, perf |
| Service-level tests | autoscaling, E2E latency, QoS compliance |
| Product conclusion | first PASS / first FAIL, procurement recommendation, caveats |
