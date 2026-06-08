# KV-Cache 4 层 I/O Profiling 完整结果报告

> **For Hermes:** 4 层 I/O profiling 完整数据集 — trace replay (BurstGPT) + 软件层 + 块层 + 设备层全部同步开。

**跑测试时间:** 2026-06-08 (3 个 run 全部完成)
**测试方法:** `--io-trace-log` + `--enable-latency-tracing` (bpftrace) + iostat/pidstat/perf,全部同步开
**Run ID 后缀:** `_full` 表示 4 层 profiling wrapper(`scripts/run_full_profiling.sh`)

## 4 层 Profiling 架构

| 层 | 工具 | 数据源 |
|---|---|---|
| **L4 KV object** | benchmark JSON/XLSX | 每次跑产生 |
| **L3 filesystem** | `--io-trace-log` | `kv_trace.csv.zst` |
| **L2 block layer** | bpftrace `storage_latency_stack.bt` | Q2D/D2C 直方图 + 自动蒸馏 fio |
| **L1 device** | iostat + pidstat + perf | 时间序列 + CPU 性能计数器 |

## 数据集(全部3 个 run 完成)

### Run 1 — 70B TP8 CPU0 users=6 trace replay ✅

**目录:** `results/kvcache-profile/profiling/burstgpt_70b_users6_full_20260608_113434/`

| 文件 | 大小 | 说明 |
|---|---|---|
| `iostat.log` | 3.3 MB | nvme1n1: 12240 r/s avg, 152 MB/s avg, %util 30.9% |
| `pidstat.log` | 1.2 MB | 进程级 I/O 计数器 |
| `perf.log` | 888 B | perf_event_paranoid=-1 后才能跑(部分事件需 sudo) |
| `kv_trace.csv.zst` | 537 KB | 94883 ops (85458 Read + 9425 Write) |
| `round1_bench.log` | 117 KB | trace 模式跑 (NullBackend, lat=0) |
| `round2_bench.log` | 132 KB | 真实 I/O 模式跑 (含 bpftrace) |

**关键 KV object 数据(70B users=6 真实 I/O 模式):**
- 3422 requests,Read Dev P95 = 96.53 ms,Write Dev P95 = 114.02 ms
- Cache hit rate 97.71%
- 887 GB read + 78 GB write (5 分钟)

**I/O Pattern (trace 模式):**
- 94883 ops,90.1% Read / 9.9% Write
- Tier-2 97.6% + Tier-0 2.4% (无 Tier-1,因为 --cpu-mem-gb 0)
- Phase: 90.1% Decode + 9.9% Prefill (无 Evict)
- Object size mean 31.2 MB, P95 77.9 MB, P99 91.8 MB, max 133.1 MB

**fio job file:** `kv_cache_benchmark/fio_kv_cache_workload_20260608_114442.ini`
- `rwmixread=91` (91% 读密集)
- `bssplit=4k/1:8k/1:16k/1:32k/1:64k/1:128k/97,...` (128KiB 为主)
- `iodepth=32768` (用 P50 QD 计算,可能过大)

### Run 2 — 70B TP8 CPU0 users=8 trace replay ✅

**目录:** `results/kvcache-profile/profiling/burstgpt_70b_users8_full_20260608_114604/`

| 文件 | 大小 | 说明 |
|---|---|---|
| `iostat.log` | 3.3 MB | nvme1n1: 14422 r/s avg, 172 MB/s avg, %util 30.4% |
| `pidstat.log` | 1.5 MB | 进程级 I/O 计数器 |
| `perf.log` | 836 B | perf_event_paranoid=-1 |
| `kv_trace.csv.zst` | 539 KB | 94883 ops (与 users=6 相同 trace replay) |
| `round1_bench.log` | 117 KB | trace 模式跑 |
| `round2_bench.log` | 132 KB | 真实 I/O 模式跑 (含 bpftrace) |

**关键 KV object 数据(70B users=8 真实 I/O 模式):**
- 3395 requests, Read Dev P95 = 164.63 ms, Write Dev P95 = 175.41 ms
- Cache hit rate 97.79%
- fio job file: `fio_kv_cache_workload_20260608_115613.ini`

### Run 3 — 8B TP8 CPU0 users=8 trace replay ✅

**目录:** `results/kvcache-profile/profiling/burstgpt_8b_users8_full_20260608_114639/`

| 文件 | 大小 | 说明 |
|---|---|---|
| `iostat.log` | 3.3 MB | nvme1n1: 15654 r/s avg, 185 MB/s avg, %util 34.0% |
| `pidstat.log` | 1.5 MB | 进程级 I/O 计数器 |
| `perf.log` | 836 B | perf_event_paranoid=-1 |
| `kv_trace.csv.zst` | 565 KB | 94801 ops (比 70B 略少) |
| `round1_bench.log` | 117 KB | trace 模式跑 |
| `round2_bench.log` | 132 KB | 真实 I/O 模式跑 (含 bpftrace) |

**关键 KV object 数据(8B users=8 真实 I/O 模式):**
- 3395 requests, Read Dev P95 = 67.60 ms, Write Dev P95 = 180.22 ms
- Cache hit rate 97.86%
- fio job file: `fio_kv_cache_workload_20260608_115648.ini`

## 跨 run 对比表(完整 burstgpt trace replay 梯度)

| 配置 | users | requests | Read Dev P95 | Write Dev P95 | Cache Hit | Status |
|---|---:|---:|---:|---:|---:|:---:|
| 8B users=2 (历史) | 2 | 5748 | 17.96 ms | 18.90 ms | 97.75% | PASS |
| **8B users=8 (full)** | 8 | 3395 | **67.60 ms** | **180.22 ms** | 97.86% | PASS |
| **70B users=2 (历史)** | 2 | 2421 | 41.85 ms | 18.68 ms | 97.86% | PASS |
| **70B users=4 (历史)** | 4 | 2490 | 92.67 ms | 125.53 ms | 97.74% | PASS |
| **70B users=6 (bursttrace)** | 6 | 3377 | **96.10 ms** | **127.60 ms** | 97.70% | PASS |
| **70B users=6 (full-profile)** | 6 | 3422 | **96.53 ms** | **114.02 ms** | 97.71% | PASS |
| **70B users=8 (历史)** | 8 | 3395 | 115.34 ms | 177.22 ms | 97.79% | PASS |
| **70B users=8 (full)** | 8 | 3395 | **164.63 ms** | **175.41 ms** | 97.79% | PASS |

## I/O Pattern 对比 (Decode 阶段,trace模式)

| 配置 | total ops | decode reads | prefill writes | mean size | P95 size | max size |
|---|---:|---:|---:|---:|---:|---:|
| 8B users=8 (full) | 94,801 | 85,383 | 9,418 | 12.5 MB | 31.2 MB | 133 MB |
| 70B users=6 (full) | 94,883 | 85,458 | 9,425 | 31.2 MB | 77.9 MB | 133 MB |
| 70B users=8 (full) | 94,883 | 85,458 | 9,425 | 31.2 MB | 77.9 MB | 133 MB |

## 设备层对比(nvme1n1,iostat)

| 配置 | r/s avg | wkB/s avg | %util avg | %util P95 |
|---|---:|---:|---:|---:|
| ShareGPT users=2 | 388 | 27 MB/s | 2.3% | 8.0% |
| 8B BurstGPT users=2 | 17,694 | 208 MB/s | 55.0% | 69.2% |
| 8B BurstGPT users=8 (full) | 15,654 | 185 MB/s | 34.0% | 69.2% |
| 70B BurstGPT users=6 (full) | 12,240 | 153 MB/s | 30.9% | 71.4% |
| 70B BurstGPT users=8 (full) | 14,422 | 172 MB/s | 30.4% | 68.8% |

## 关键发现

1. **70B 真实 BurstGPT trace 在 users=2/4/6/8 全 PASS** — 之前47 JSON 没 users=6,现在补完
2. **Cache hit rate 稳定在 97.7%** — 重复 trace 几乎都命中,真实流量来自 cache eviction
3. **Trace 模式产出 ~94800 ops/300s ≈ 316 ops/sec** — 平均每请求触发 ~30 个 KV cache I/O
4. **70B object size P95 = 78MB,8B = 31MB** — 70B 大约 2.5× 8B(符合 LLM 模型规模比)
5. **70B IOPS(12-14k)低于 8B(15-17k)** — 因为 70B object 大,每个请求触发的 I/O 次数更少
6. **SSD 利用率稳定 30-35%** — 仍有大量余量,AI SSD 选型不是瓶颈
7. **fio job file:** 91% 读密集,128KiB 为主块大小 — 适合 fio sweep 验证 SSD 极限

## 下一步

- 蒸馏 fio sweep (iodepth 32/64/128/256/1024) 用蒸馏的 .ini
- 比较 70B vs 8B object size 差异
- 把新数据点接进现有 `io_profile_summary.csv` (已 17 → 21 行, +4 行)
- 出 v2 PDF 报告

## 相关产物

- **报告:** `docs/kvcache-io-profiling-visual-analysis-2026-06-08.md`
- **新文档:** 本文档
- **I/O pattern 图 (PNG+MD):** `results/kvcache-profile/io_pattern_*.{png,md}`
- **iostat 摘要:** `results/kvcache-profile/iostat_summary_*.csv`
- **fio job files:** `kv_cache_benchmark/fio_kv_cache_workload_*.ini`
- **脚本:**
  - `scripts/run_full_profiling.sh` (4 层 profiling wrapper)
  - `scripts/analyze_io_trace.py` (io-trace-log CSV 分析)
  - `scripts/append_to_io_profile_summary.py` (新数据接进 CSV)
  - `scripts/summarize_iostat_pidstat.py` (iostat/pidstat 摘要)
- **数据目录:**
  - `results/kvcache-profile/profiling/burstgpt_70b_users6_full_20260608_113434/`
  - `results/kvcache-profile/profiling/burstgpt_70b_users8_full_20260608_114604/`
  - `results/kvcache-profile/profiling/burstgpt_8b_users8_full_20260608_114639/`
- **汇总表(已更新):**
  - `docs/assets/kvcache-io-profiling/io_profile_summary.csv` (21 行)
  - `docs/assets/kvcache-io-profiling/iostat_summary.csv` (11 行,去重后)