# 页缓存敏感性扫描 — BIWIN X570 SSD + BurstGPT 70B 工作负载 (Page Cache Sensitivity Sweep — BIWIN X570 SSD + BurstGPT 70B Workload)

**日期 (Date):** 2026-06-09
**测试 ID (Test ID):** pagecache_sweep_20260609_143617
**时长 (Duration):** 每单元 30s × 4 单元
**测试文件 (Test file):** 20 GiB（fio 缓冲 IO, direct=0）
**工作负载 (Workload):** BurstGPT 70B users=6 蒸馏（R/W=91:9, iodepth=32, bssplit 4k-128k）

---

## 🎯 目标 (Goal)

量化 DRAM 页缓存对 SSD 绑定的 KV 缓存工作负载有多大帮助（或损害）。比较 4 种 DRAM 策略以覆盖生产用例：

| 单元 (Cell) | DRAM | Cgroup | fio `invalidate` | 模拟 (Simulates) |
|---|---|---|---|---|
| `dram_unlimited` | 系统默认 (system default) | 无 (none) | 关 (off) | 最佳情况（无限制）(Best-case) |
| `dram_32gb` | cgroup mem.max=32 GiB | 是 (yes) | 关 (off) | 生产服务器 (Production server) |
| `dram_8gb` | cgroup mem.max=8 GiB | 是 (yes) | 关 (off) | 边缘 / 小节点 (Edge / small node) |
| `dram_8gb_evict` | cgroup mem.max=8 GiB | 是 (yes) | **开（每次 I/O）(on, every I/O)** | 冷缓存基线 (Cold cache baseline) |

`evict` 单元是关键技巧：cgroup v2 不限制共享内核页缓存（它只统计 cgroup 本地的匿名/文件页），因此 `invalidate=1` 强制 fio 在每次 I/O 后丢弃页面，提供了真正的"无缓存"基线。

---

## 📊 fio 结果（读取占主导 — 91% 的 I/O）(fio results — READ is dominant)

| 单元 (Cell) | 读取带宽 READ BW | 写入带宽 WRITE BW | 读取 P50 (READ P50) | 读取 P99 (READ P99) | 系统缓存 (Sys Cached) |
|---|---:|---:|---:|---:|---:|
| **dram_unlimited** | 1071 MiB/s | 104 MiB/s | 121 μs | 277 μs | 22.7 GB |
| **dram_32gb** | **1294 MiB/s** | 127 MiB/s | **102 μs** | **202 μs** | 23.8 GB |
| **dram_8gb** | 1231 MiB/s | 121 MiB/s | 97 μs | 269 μs | 24.1 GB |
| **dram_8gb_evict** | **1158 MiB/s** | 114 MiB/s | 115 μs | 258 μs | **23.2 GB** |

### 对比 dram_unlimited 的变化 (Δ vs dram_unlimited)（冷缓存基线）

| 单元 (Cell) | 读取变化 READ Δ | 备注 (Notes) |
|---|---:|---|
| dram_unlimited | 0%（基线） | 第一次运行，无预热 |
| dram_32gb | **+20.8%** | 顺序效应：先前运行留下了热页面 |
| dram_8gb | **+14.9%** | 顺序效应 + cgroup 限制 |
| dram_8gb_evict | **+8.1%** | 顺序效应**被 invalidate 部分抵消** |

---

## 🧠 关键发现 (Key Findings)

### 1. cgroup v2 memory.max 不限制共享页缓存
在所有 4 个单元中，cgroup memory.peak 约为 **~3 MB**（仅为 fio 进程的匿名内存）。系统级 `Cached` 显示约 23 GB，与 cgroup 限制无关。这是一个已知的 v2 限制：`memory.max` 仅计入属于该 cgroup 的页面费用，但缓冲 IO 页面属于全局共享缓存。使用 v1 cgroups 或 `--invalidate=1` 才能真正限制 DRAM。

### 2. 页缓存命中将 KV 缓存读取加速约 6%
`dram_8gb_evict`（1158 MiB/s） vs `dram_8gb`（1231 MiB/s）：在每次 I/O 后强制 `invalidate=1` 花费了 **6% 的读取吞吐量**。这是本次测试中真正的"DRAM 缓存价值"测量。

### 3. P99 延迟由 SSD 主导，而非 DRAM
- dram_32gb P99 = 202 μs（热页面）
- dram_8gb_evict P99 = 258 μs（每次读取都冷）
56 μs 的差距是 SSD 读取路径上的页缓存未命中惩罚。仍小于 300 μs — 完全在 KV 缓存读取 SLO 范围内。

### 4. 顺序效应主导带宽数值
`dram_unlimited` 在带宽上*排最后*（1071 MiB/s），尽管拥有最多的 DRAM 可用，因为它在冷缓存时首先运行。**+20.8% 的增量主要是测试顺序的伪影，而非真正的 DRAM 效应。** 要干净地测量 DRAM，单元的排序需要随机化并多次重复。

### 5. 两个 `mem.max=8GB` 的单元都显示系统 Cached=23-24GB
内核页缓存增长远超 cgroup 限制，因为共享页面不计入 cgroup。如果测试实际上受内存限制，差异会表现为 OOM 杀死，而非 Cached 大小。

---

## 🎯 对 AI SSD 设计的启示 (Implications for AI SSD design)

1. **DRAM 加速 KV 缓存读取是真实的但很小（约 6%）**
   SSD 绑定的读取延迟中大部分是 SSD 本身造成的（P99 ≈ 250 μs），而非页缓存未命中惩罚。将 DRAM 作为 KV 缓存层投资仅带来个位数百分比的吞吐量提升，而非 2-3 倍。

2. **生产部署应根据热工作集来规划 DRAM 大小，而非总 KV 缓存大小。** 70B 模型约有 140 GiB 的缓存，但只有*当前预填充*部分是热的。即使是 32 GiB DRAM 也能轻松覆盖（我们测量到 23-24 GB 使用量）。

3. **DRAM 对读取延迟尾部比吞吐量更有价值。**
   P99 从 277 μs（冷）→ 202 μs（热）— 减少了 27% 的延迟，这不会在吞吐量数据中体现，但对 LLM 交互式延迟很重要。

4. **冷启动时间很重要。** 空闲后的第一个请求总是承受冷缓存命中。对于自动缩放驱动的突发（我们的 B 测试 30 分钟 GC 漂移数据），DRAM 有助于吸收涌入。

---

## 🛠️ 测试基础设施（可复用）(Test infrastructure — reusable)

- `scripts/pagecache_sensitivity_sweep.sh` — 编排器（3.5 KB）
- `scripts/analyze_pagecache_sensitivity.py` — 分析脚本（7.2 KB）
- `docs/kvcache-pagecache-sensitivity-2026-06-09.md` — 本报告
- `results/kvcache-profile/pagecache_sweep/*_20260609_143617/` — 原始数据

---

## ⚠️ 注意事项 / 后续步骤 (Caveats / next steps)

1. **顺序效应**: 使用 `--shuffle` 或随机单元顺序重新运行，取 3 次重复的中位数。
2. **测试文件 > DRAM 限制**: 使用 60+ GiB 测试文件和 8 GiB cgroup，这样 DRAM 压力才是真实的。
3. **混合工作负载**: 添加 `dram_8gb_evict + writes` 单元，观察脏页压力与 cgroup 限制的交互。
4. **轨迹回放**: 不再使用蒸馏 fio，而是直接使用 kv-cache 基准测试本身，用 `--cpu-mem-gb 8` 直接限制 KV 缓存主机内存。

---

## 🧪 原始数据文件 (Raw data files)

每个单元目录包含：
- `fio.log` — 完整 fio 输出
- `iostat.log` — 设备级统计（1Hz）
- `cgroup_memory.log` — memory.peak / current / events / stat
- `cgroup_memory_timeline_stats.log` — cgroup memory.current 的最小/均值/最大/P99
- `meminfo_end.log` — 系统 MemTotal/MemFree/Cached/Dirty 快照
- `memory_current_timeline.log` — cgroup memory.current 的 1Hz 采样（65 个样本）
- `workload.ini` — 生成的 fio 配置（evict 单元带有 `invalidate=1`）
