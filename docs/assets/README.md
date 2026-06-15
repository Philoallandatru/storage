# docs/assets — Visualization Index

> 14 张 IO profiling 图, 全部已 commit 入版本。覆盖 MLPerf Storage KV-cache cross-vendor 4 盘对比 + IO profiling 业务级图。

## Cross-vendor 4 盘对比图 (charts/)

**4 块候选盘**: `biwin_x570` (Biwin X570 1TB, mainstream) / `seagate_fc530` (Seagate FC530 1TB, high-end Phison E18) / `wd_sn570` (WD SN570 1TB, entry-level DRAM-less) / `zhitai_ti600` (ZhiTai Ti600 1TB, domestic YMTC NAND)

| # | 文件 | 类型 | 故事 | 对应报告 |
|---|---|---|---|---|
| 01 | [charts/01_k4_k5_bw_compare.png](charts/01_k4_k5_bw_compare.png) | 4 盘 read BW 对比 | K4 (8B×16u×120s) + K5 (70B×4u×180s) + K4 GC-drift (1200s) — Biwin X570 第一 | [kv-cache-4disk-K4-headline-2026-06-10.md](../kv-cache-4disk-K4-headline-2026-06-10.md), [kv-cache-4disk-K5-headline-2026-06-10.md](../kv-cache-4disk-K5-headline-2026-06-10.md) |
| 02 | [charts/02_k4_gc_p99_drift.png](charts/02_k4_gc_p99_drift.png) | 时间序列 | K4 GC-drift 1200s read p99 latency 漂移 — 揭示长稳态退化 | [kv-cache-cross-vendor-2026-06-10.md](../kv-cache-cross-vendor-2026-06-10.md) |
| 03 | [charts/03_cliff_detection.png](charts/03_cliff_detection.png) | 时序 + 标注 | read BW 时序 + cliff marker — SLC cache 跌落点检测 | [kv-cache-cross-vendor-2026-06-10.md](../kv-cache-cross-vendor-2026-06-10.md) |
| 04 | [charts/04_io_pattern_boxplots.png](charts/04_io_pattern_boxplots.png) | 4 盘分布 | request size + await boxplots 4 盘 | [kv-cache-io-pattern-analysis-2026-06-10.md](../kv-cache-io-pattern-analysis-2026-06-10.md) |
| 05 | [charts/05_summary_ranking.png](charts/05_summary_ranking.png) | 热力图 | **决策图**: 6-metric 4 盘 ranking heatmap (BW / IOPS / p99 / hicache cold / 等) | [kv-cache-4disk-K4-headline-2026-06-10.md](../kv-cache-4disk-K4-headline-2026-06-10.md) |
| 06 | [charts/06_write_p99_drift.png](charts/06_write_p99_drift.png) | 时间序列 | write service-time 漂移 — GC 影响最显著的指标 | [kv-cache-cross-vendor-2026-06-10.md](../kv-cache-cross-vendor-2026-06-10.md) |
| 07 | [charts/07_long_drift_compare.png](charts/07_long_drift_compare.png) | 4 盘时序 | K4 30-min 4 盘长稳态 — **Biwin/Seagate 30 min 后实际 TIED** | [kv-cache-4disk-K4-30min-drift-2026-06-10.md](../kv-cache-4disk-K4-30min-drift-2026-06-10.md) |
| 08 | [charts/08_duration_bars.png](charts/08_duration_bars.png) | 柱状图 | K4 多窗口 (5/10/30 min) BW 柱状图 | [kv-cache-4disk-K4-30min-drift-2026-06-10.md](../kv-cache-4disk-K4-30min-drift-2026-06-10.md) |

## IO profiling / 业务级图 (kvcache-io-profiling/)

| # | 文件 | 故事 | 对应报告 |
|---|---|---|---|
| 01 | [kvcache-io-profiling/burstgpt_users_gradient_latency.png](kvcache-io-profiling/burstgpt_users_gradient_latency.png) | BurstGPT users × latency 渐变 (用户数 vs P50/P95/P99) | [kvcache-io-profiling-visual-analysis-2026-06-08.md](../kvcache-io-profiling-visual-analysis-2026-06-08.md) |
| 02 | [kvcache-io-profiling/iostat_await_utilization.png](kvcache-io-profiling/iostat_await_utilization.png) | iostat await / util 时间序列 (多盘叠加) | [kvcache-io-profiling-visual-analysis-2026-06-08.md](../kvcache-io-profiling-visual-analysis-2026-06-08.md) |
| 03 | [kvcache-io-profiling/kv_object_device_p95_comparison.png](kvcache-io-profiling/kv_object_device_p95_comparison.png) | KV object store vs device local p95 latency 对比 | [kvcache-io-profiling-visual-analysis-2026-06-08.md](../kvcache-io-profiling-visual-analysis-2026-06-08.md) |
| 04 | [kvcache-io-profiling/object_latency_vs_d2c_read.png](kvcache-io-profiling/object_latency_vs_d2c_read.png) | object store latency vs D2C (device-to-cache) read | [kvcache-io-profiling-visual-analysis-2026-06-08.md](../kvcache-io-profiling-visual-analysis-2026-06-08.md) |
| 05 | [kvcache-io-profiling/storage_traffic_workload_comparison.png](kvcache-io-profiling/storage_traffic_workload_comparison.png) | storage traffic pattern × workload type (训练/checkpointing/KV-cache) | [kvcache-io-profiling-visual-analysis-2026-06-08.md](../kvcache-io-profiling-visual-analysis-2026-06-08.md) |

> 每个 PNG 在 `kvcache-io-profiling/` 都有同名 SVG 源文件, 可用 Inkscape/Illustrator 编辑。

## 复现

### charts/ (图 01-06)

```bash
cd /home/ficus/llm/storage
source .venv/bin/activate
python ~/.hermes/skills/mlperf-storage-bench/scripts/render_kv_cache_charts.py
# 输出: docs/assets/charts/01-06 (覆盖式重生成, 可重复)
# 依赖: results/cross_vendor/kv_cache_k4_only/{biwin_x570,seagate_fc530,wd_sn570,zhitai_ti600}/K4_16u_llama3.1-8b_120s/
```

### charts/ (图 07-08: 30-min drift)

不通过脚本生成。来自 commit `2060baa` (K4 30-min 长稳态测试) 的手工绘图。如需重生成:
```bash
# 原始数据: results/cross_vendor/kv_cache_k4_30min_drift/{disk}/K4_30min_*/
# 绘图: matplotlib 手工脚本 (未 commit, 在 commit 2060baa 里 inline)
```

### kvcache-io-profiling/ (业务级 5 张图 + SVG)

来自 commit `a1751ef` (IO profiling visual analysis) 的 matplotlib 手工绘图。如需重生成:
```bash
# 原始数据: results/kvcache-profile/  (bpftrace / fio / io_pattern 数据)
# 绘图: matplotlib 手工脚本 (commit a1751ef 里 inline)
```

## 推荐阅读路径

1. **决策导向** (产品/采购): 先看 `charts/01_k4_k5_bw_compare.png` → `charts/05_summary_ranking.png` → `charts/07_long_drift_compare.png` → [docs/ai-ssd-kvcache-integrated-prestudy-report-2026-06-13.md](../ai-ssd-kvcache-integrated-prestudy-report-2026-06-13.md)
2. **方法学导向** (工程师): 先看 `charts/02_k4_gc_p99_drift.png` → `charts/03_cliff_detection.png` → `charts/06_write_p99_drift.png` → [docs/kv-cache-cross-vendor-2026-06-10.md](../kv-cache-cross-vendor-2026-06-10.md)
3. **业务级 IO 特征** (架构师): 先看 `kvcache-io-profiling/storage_traffic_workload_comparison.png` → `iostat_await_utilization.png` → [docs/kvcache-io-profiling-visual-analysis-2026-06-08.md](../kvcache-io-profiling-visual-analysis-2026-06-08.md)
