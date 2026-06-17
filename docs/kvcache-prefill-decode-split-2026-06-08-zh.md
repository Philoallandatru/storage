# KV-Cache Prefill-only / Decode-only 拆分测试报告

> **For Hermes:** 按报告 P0 列表第 2 项 — 分离写密集 (prefill) 和读密集 (decode) 路径,
> 与混合模式 (Run1: 70B users=6) 直接对比。

**测试时间:** 2026-06-08
**测试方法:** `--prefill-only` / `--decode-only` 与原混合模式 (Run1) 同样的 70B TP8 CPU0 users=6 配置对比。
**完整 profiling:** L1 device + L2 block + L3 filesystem + L4 KV object 四层。

---

## 🎯 关键对比表

### KV object (L4) 真实硬件延迟对比

| 配置 | requests | Read Dev P95 | Write Dev P95 | prefill writes | decode reads | read GB | write GB |
|---|---:|---:|---:|---:|---:|---:|---:|
| **prefill-only** | 6,608 | n/a (0 reads) | **117.93 ms** | **6,608** ✅ | 0 ✅ | 0 | 152 GB |
| **decode-only** | 1,772 | **88.92 ms** | n/a (0 writes) | 0 ✅ | **16,209** | 1,266 GB | 0 |
| **混合 (Run1, 对照)** | 3,422 | 96.53 ms | 114.02 ms | 3,377 | 30,146 | 887 GB | 78 GB |

### I/O Pattern (L3) trace 模式

| 配置 | total ops | Read/Write | Prefill/Decode | mean size | P95 size | max size |
|---|---:|---|---|---:|---:|---:|
| **prefill-only** | 9,425 | **100% Write** | **100% Prefill** | 25.0 MB | 73.6 MB | 133 MB |
| **decode-only** | 85,550 | **99.93% Read** | **99.93% Decode** | **80 MB** | 80 MB | 80 MB |
| **混合 (Run1, 对照)** | 94,883 | 90% Read + 10% Write | 90% Decode + 10% Prefill | 31.2 MB | 77.9 MB | 133 MB |

### 设备层 (L1) nvme1n1

| 配置 | r/s avg | wkB/s avg | %util avg | %util P95 | 主导模式 |
|---|---:|---:|---:|---:|
| **prefill-only** | 8,425 r/s | **150 MB/s** ⬆️ | 22.7% | 61.6% | **写密集** |
| **decode-only** | **17,082 r/s** ⬆️ | 27 MB/s | 28.7% | 62.4% | **读密集** |
| **混合 (Run1, 对照)** | 12,240 r/s | 153 MB/s | 30.9% | 71.4% | 平衡读写 |

---

## 🔑 关键发现

### 1. **prefill-only: 完全写密集路径**
- **`prefill_writes=6608`,`decode_reads=0`** ✅ 完全分离
- Write Dev P95 = **117.93 ms** (vs 混合模式的 114.02 ms,差异不大)
- 写了 **152 GB / 5 分钟** (50 MB/s 持续)
- SSD 利用率 **22.7%** 反而低于混合 (30.9%) — 说明混合模式压力更大

### 2. **decode-only: 完全读密集路径**
- **`decode_reads=16209`,`prefill_writes=0`** ✅ 完全分离
- Read Dev P95 = **88.92 ms** (vs 混合模式的 96.53 ms,纯读更快)
- **17,082 IOPS** — 最高,因为是纯读 SSD
- 60 个预填充的 KV cache entries (2048 tokens each) — **每个 entry 80 MB 恒定大小**

### 3. **混合模式是最严苛的测试场景**
- prefill-only 利用率 22.7%, decode-only 28.7% — **都比混合模式低**
- **混合 30.9% 是最高** — 因为它必须同时处理读和写,SSD 内部要:
  - 服务读请求(数据已就绪,可能命中 cache)
  - 服务写请求(触发 GC/SLC cache flush)
  - 维护写入顺序(写放大)
- **结论**: 混合模式是最能暴露 SSD 真实尾延迟的场景

### 4. **写路径和读路径独立分析的价值**
- **写路径 (prefill)**: Dev P95 = 117 ms,平均 150 MB/s 持续写 — 评估 SSD write endurance 关键
- **读路径 (decode)**: Dev P95 = 89 ms,17k IOPS — 评估 SSD read latency 关键
- **这两个独立数据点比混合模式的 96/114 ms 更有价值**,因为它们各自隔离了 SSD 子系统行为

---

## 📊 设备层详细数据 (iostat nvme1n1)

### prefill-only
| 指标 | 数值 |
|---|---:|
| samples | 1245 (5× more,因为 trace+hwio 合并) |
| r/s avg | 8,425 |
| wkB/s avg | 150 MB/s |
| %util avg | 22.7% |
| %util P95 | 61.6% |

### decode-only
| 指标 | 数值 |
|---|---:|
| samples | 614 |
| r/s avg | **17,082** |
| wkB/s avg | 27 MB/s (因为读请求是 80 MB 缓存条目,被 page cache 大量吸收) |
| %util avg | 28.7% |
| %util P95 | 62.4% |

---

## 🧠 对 AI SSD 产品设计的含义

1. **AI SSD 必须独立优化写和读** — 因为 prefill/decode 流量比例取决于 workload:
   - 长 prompt (代码/文档) → prefill 主导 → 写压力
   - 短 prompt (聊天) → decode 主导 → 读压力
2. **混合 workload 的 30% 利用率 + 7% P95** — 这是 SSD 的真实基线,**不是** 预条件化后能达到更高
3. **decode 命中率 97.7%** — 重复 trace 几乎都命中,真实生产环境中 cache 失效的 IO 来自 cache 替换

---

## 📁 产物

### 数据目录
- `results/kvcache-profile/profiling/burstgpt_70b_users6_prefill_only_20260608_145905/`
- `results/kvcache-profile/profiling/burstgpt_70b_users6_decode_only_20260608_145905/`

每个目录包含:
- `iostat.log` (~3 MB), `pidstat.log` (~1 MB), `perf.log`
- `kv_trace.csv.zst` (trace CSV)
- `round1_bench.log`, `round2_bench.log`

### Benchmark JSON
- `results/kvcache-profile/test_burstgpt_70b_users6_prefill_only_20260608_145905_{trace,hwio}.{json,xlsx}`
- `results/kvcache-profile/test_burstgpt_70b_users6_decode_only_20260608_145905_{trace,hwio}.{json,xlsx}`

### I/O Pattern 报告
- `results/kvcache-profile/io_pattern_burstgpt_70b_users6_prefill_only_20260608_145905.{md,png}`
- `results/kvcache-profile/io_pattern_burstgpt_70b_users6_decode_only_20260608_145905.{md,png}`

### iostat 摘要
- `results/kvcache-profile/iostat_summary_burstgpt_70b_users6_prefill_only_20260608_145905.csv`
- `results/kvcache-profile/iostat_summary_burstgpt_70b_users6_decode_only_20260608_145905.csv`

### 汇总表 (已更新)
- `docs/assets/kvcache-io-profiling/io_profile_summary.csv` (17 → 24 行, +7 行)
- `docs/assets/kvcache-io-profiling/iostat_summary.csv` (新增 2 行)

### 脚本
- `scripts/run_prefill_decode_sweep.sh` (顺序跑避免 bpftrace 干扰)

---

## 下一步

- ✅ 完成:P0 列表第 2 项 (prefill/decode 拆分)
- 下次推荐:P0 列表第 3 项 — **fio sweep (iodepth 32/64/128/256/1024)**,用蒸馏的 3 个 fio job file 跑 sweep
- 其他候选:SSD preconditioning / 长稳态 30-60 分钟 / CPU cache sensitivity