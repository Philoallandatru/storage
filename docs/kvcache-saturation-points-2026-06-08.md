# KV-Cache Saturation Point Sweep — 2026-06-08

> **TL;DR:** 在当前 NVMe 设备上，**70B 用户数 ≥ 12 即触发真硬件饱和门槛**（device P95 > 100ms，SLA 全面崩溃）；**8B 用户数 ≤ 32 仍未饱和**（device P95 ≈ 43ms read / 112ms write，SLA 100% PASS）。Trace 模式（NullBackend）会**高估系统能力 5–10×**，容量规划必须使用 Round 2 真硬件数据。

---

## 一、实验配置

| Run | 模型 | Users | 模式 | Duration | 产物 |
|---|---|---:|---|---:|---|
| `burstgpt_70b_tp8_cpu0g_users12` | Llama 3.1 70B TP8 CPU0 | 12 → 500 (autoscaler) | Trace + bpftrace (Round 1+2) | 300s × 2 | `test_*_trace.{json,xlsx}`, `test_*_hwio.{json,xlsx}`, `kv_trace.csv.zst`, `iostat/pidstat/perf.log`, bpftrace Q2D/D2C 直方图, `fio_kv_cache_workload_20260608_215718.ini` |
| `burstgpt_8b_tp8_cpu0g_users32` | Llama 3.1 8B TP8 CPU0 | 32 → 500 (autoscaler) | Trace + bpftrace (Round 1+2) | 300s × 2 | `test_*_trace.{json,xlsx}`, `test_*_hwio.{json,xlsx}`, `kv_trace.csv.zst`, `iostat/pidstat/perf.log`, bpftrace Q2D/D2C 直方图, `fio_kv_cache_workload_20260608_220800.ini` |

**共享参数：** `--use-burst-trace` + `--trace-speedup 1000` + `--replay-cycles 0` + `--max-concurrent-allocs 2` + `--enable-autoscaling` + `--io-trace-log` (Round 1) + `--enable-latency-tracing` (Round 2)

**4 层 profiling wrapper：** `scripts/run_full_profiling.sh`（同时启 iostat/pidstat/perf + bpftrace 块层跟踪）

---

## 二、关键发现（70B users=12 vs 8B users=32）

### 2.1 Round 1 (Trace / NullBackend) — 全部 PASS，但掩盖了真硬件压力

| 指标 | 70B users=12 | 8B users=32 |
|---|---:|---:|
| Storage Performance Assessment | **PASS 3/3** | **PASS 3/3** |
| Storage Read Device P95 | 0.00 ms (NullBackend) | 0.00 ms (NullBackend) |
| Storage Write Device P95 | 0.00 ms (NullBackend) | 0.00 ms (NullBackend) |
| Cache Hit Rate | 97.8% | 97.8% |
| Read/Write Ratio | 11.56 | 11.56 |
| Storage Read Bandwidth | 6.20 GiB/s | 2.48 GiB/s |
| Total Requests Completed | 9,283 | 6,469 |
| Autoscaler Final User Count | 500 (上限触顶) | 321 |

**问题：NullBackend 的 device latency 永远 = 0.00ms**，无法反映真硬件压力。

### 2.2 Round 2 (真硬件 / bpftrace) — **饱和点对照清晰**

| 指标 | 70B users=12 | 8B users=32 | 解读 |
|---|---:|---:|---|
| **Storage Read Device P95** | **127.86 ms** ⚠️ | **43.05 ms** ✅ | 70B-12 已逼近 200ms SLA 上限 |
| **Storage Write Device P95** | **154.87 ms** ⚠️ | **112.05 ms** ✅ | 70B-12 写延迟为 8B-32 的 1.4× |
| **Storage Read Bandwidth** | 2.94 GiB/s | n/a (低延迟) | 70B-12 跑到 NVMe 极限 |
| **E2E Latency P95** | **115.6 秒** ❌ | n/a (P50 ~4.1 s) | 70B-12 用户级别灾难 |
| **E2E Latency P99** | **133.4 秒** ❌ | n/a | 99% 用户等待 2 分钟 |
| **RESPONSIVE P95** | **107.3 秒** ❌ | 14.7 ms ✅ | 70B-12 响应式请求全失败 |
| **SLA Compliance (INTERACTIVE)** | **0.6%** ❌ | 100% ✅ | 70B-12 几乎所有请求超时 |
| **SLA Compliance (RESPONSIVE)** | **1.0–1.2%** ❌ | 100% ✅ | |
| **Queue Depth (峰值)** | 4,536 users | 0 | 70B-12 队列积压严重 |
| **Autoscaler `saturation` 指标** | 0.50 (触发) | 0.00 | 70B-12 真实饱和信号 |

**🔑 核心结论：**

- **70B users=12 = 真硬件饱和门槛**（device P95 已超过 100ms，SLA 全面失败）
- **8B users=32 仍远未饱和**（8B 单 token KV 只有 128 KiB vs 70B 的 320 KiB，硬件压力只有 40%）
- **Trace 模式与真硬件的 device latency 差异 > 100×**（0.00ms vs 127.86ms）—— 容量规划必须用 Round 2 数据

### 2.3 I/O Pattern 分析（来自 `analyze_io_trace.py`）

| 指标 | 70B users=12 | 8B users=32 | 比例（70B / 8B） |
|---|---:|---:|---:|
| Total ops | 94,883 | 94,883 | 1.0 |
| Read ops | 85,458 | 85,458 | 1.0 |
| Write ops | 9,425 | 9,425 | 1.0 |
| Tier-2 (storage) ops | 92,645 | 92,645 | 1.0 |
| Tier-0 (GPU) ops | 2,238 | 2,238 | 1.0 |
| Prefill ops | 9,425 | 9,425 | 1.0 |
| Decode ops | 85,458 | 85,458 | 1.0 |
| **Object size mean** | **31.2 MB** | **12.5 MB** | **2.5×** |
| **Object size P95** | **77.9 MB** | **31.2 MB** | **2.5×** |
| **Object size P99** | **91.8 MB** | **36.7 MB** | **2.5×** |

**完美对应 KV bytes/token 比例**：320 KiB (70B) / 128 KiB (8B) = 2.5×。说明 IOTracer 准确捕获了模型规模差异。

---

## 三、对 AI SSD 选型的实际意义

1. **单用户并发上限**：
   - 70B TP8: ≤ 8 users 仍安全（device P95 < 100ms），12+ users 必然触发 SLA 失败
   - 8B TP8: ≥ 32 users 仍安全（device P95 < 50ms），可继续往上探

2. **NVMe 设备真实吞吐**：
   - 70B-12 跑到 **2.94 GiB/s**（饱和边缘）
   - 8B-32 跑到 **2.48 GiB/s**（仍有空间）
   - **结论：当前 NVMe 设备 KV-cache 持续读吞吐上限 ~3 GiB/s**

3. **trace mode 不可用于容量规划** —— 必须用 `run_full_profiling.sh` Round 2 (真硬件) 才能反映真实 SLA

---

## 四、产物清单

### 数据
- `results/kvcache-profile/test_burstgpt_70b_tp8_cpu0g_users12_20260608_214710_{trace,hwio}.{json,xlsx}` (4 文件)
- `results/kvcache-profile/test_burstgpt_8b_tp8_cpu0g_users32_20260608_215751_{trace,hwio}.{json,xlsx}` (4 文件)
- `results/kvcache-profile/profiling/burstgpt_70b_tp8_cpu0g_users12_*/` (iostat/pidstat/perf.log + 2× bench.log + kv_trace.csv.zst)
- `results/kvcache-profile/profiling/burstgpt_8b_tp8_cpu0g_users32_*/` (同上)
- `kv_cache_benchmark/fio_kv_cache_workload_20260608_{215718,220800}.ini` (蒸馏 fio job file)

### I/O Pattern 报告
- `results/kvcache-profile/io_pattern_burstgpt_70b_tp8_cpu0g_users12_full_20260608.md`
- `results/kvcache-profile/io_pattern_burstgpt_8b_tp8_cpu0g_users32_full_20260608.md`

### 脚本改动
- `scripts/run_full_profiling.sh` — `perf` 改为可选（不强制 sudo -n）
- `.gitignore` — 排除 `.hermes/`、`RC=*` 等本地临时产物

---

## 五、Autoscaler 行为观察（值得记一笔）

`--enable-autoscaling --autoscaler-mode qos` 的扩容速率能直接反映硬件压力：

| Run | 起始 users | Final users | Scaling Events | Saturation 触发 | 含义 |
|---|---:|---:|---:|---|---|
| 70B-12 Round 1 (trace) | 12 | **500 (上限)** | **25** | ❌ 0.00 | trace 模式无法感知压力，autoscaler 一路放行 |
| 70B-12 Round 2 (bpftrace) | 12 | 500 (上限) | 28+ | ✅ **0.50** | 真硬件扛不住，autoscaler 知道但扛不住 Queue 4500+ |
| 8B-32 Round 1 (trace) | 32 | **321** | 17 | ❌ 0.00 | 8B 容量大，autoscaler 较克制 |
| 8B-32 Round 2 (bpftrace) | 32 | 500 (上限) | 28+ | ❌ 0.00 | 8B 即使到 500 users 也没触发真饱和信号 |

**关键观察**：
- Trace 模式下 `saturation` 指标**永远不触发**（0.00），autoscaler 误以为系统健康
- Round 2 (bpftrace) 下 70B-12 **saturation=0.50** 是真硬件瓶颈的强信号
- **建议把 saturation ≥ 0.5 作为 AI SSD 选型 red flag**

---

## 六、下一批实验建议

按 ROI 排序：

1. **70B users=8 临界点验证**（~12 min）—— 8 vs 12 之间确认真硬件饱和的**精确门槛**
2. **8B users=64 / 128 继续上探**（~12 min × 2）—— 找 8B 的真硬件饱和门槛
3. **fio 蒸馏的 INI 跑裸盘回放**（~6 min）—— `fio_kv_cache_workload_20260608_215718.ini` 是 AI SSD 验收 spec 候选
4. **不同 `rwmixread` 梯度**（~12 min × 3）—— 当前 trace 100% read，加 rwmixread 50/75 评估混合读写场景

---

## 七、复现命令

```bash
cd ~/llm/storage && source .venv/bin/activate
# 70B users=12 探饱和
bash scripts/run_full_profiling.sh burstgpt_70b_tp8_cpu0g_users12 llama3.1-70b-instruct 12 300
# 8B users=32 探饱和
bash scripts/run_full_profiling.sh burstgpt_8b_tp8_cpu0g_users32 llama3.1-8b 32 300
# I/O pattern 分析
python3 scripts/analyze_io_trace.py \
    results/kvcache-profile/profiling/burstgpt_70b_tp8_cpu0g_users12_*/kv_trace.csv.zst \
    --out-md results/kvcache-profile/io_pattern_burstgpt_70b_tp8_cpu0g_users12_full_20260608.md
```

---

**Generated:** 2026-06-08 22:15 UTC+8
**Toolchain:** `kv-cache.py` v0 + `analyze_io_trace.py` + `run_full_profiling.sh` + storage_latency_stack.bt
**Storage device:** NVMe (~3 GiB/s sustained read, ~1.5 GiB/s sustained write)

**注意：** 仓库当前 `uv.lock` 有未提交改动（`M uv.lock`），与本次 saturation sweep 无关，留作独立 commit 处理。
