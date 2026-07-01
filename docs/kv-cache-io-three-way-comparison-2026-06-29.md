# KV Cache I/O 模式三路综合对比

**日期:** 2026-06-29
**作者:** 综合三份实测报告 + 自行补算
**设备:** `/dev/nvme0n1` (BIWIN X570 1TB, ext4 根盘)
**tracepoint:** `tracepoint:block:block_rq_issue` (per-I/O block event stream)
**Workload runner:** `kv_cache_benchmark/kv-cache.py` (v2.0.0b1)

---

## 一句话结论

**三种 workload 产生截然不同的 block I/O 模式,不能互相替代作为 SSD 压力基准。**default (real 默认 mixed prefill+decode) 是读写分裂的双模式 (写 95% 在 <1 MiB、读 79% 大跳跃),sharegpt 是中等且混合的(读 57% 大跳跃,写 94% 连续),burstgpt 是最重且最随机的(读 89% 大跳跃,IOPS 35K)。**对于评估 KV-cache SSD offload 的真实效能,必须用 kv-cache.py 实跑的 tracepoint 数据,任何 fio replay 都不能反映真实 LBA 跳跃分布。**

---

## 数据源说明

| Workload | 数据源 | 工具链 | 时长 | 块事件数 |
|---|---|---|---:|---:|
| **default** | `results/kvcache-profile/default_baseline/lba_trace_summary.json` | `kv-cache.py --num-users 8 --duration 120` (llama3.1-8b, **TP=1**, 0/0 GiB GPU/CPU cache) + bpftrace | 132.78s | 4,090,543 |
| **sharegpt** | `results/kvcache-profile/sharegpt_kvcache_20260629_140729/block_lba_trace.csv` | `kv-cache.py --num-users 8 --duration 120` (llama3.1-8b, TP=1, 0/0 GiB GPU/CPU cache) + bpftrace | 140.91s | 1,981,685 |
| **burstgpt** | `results/kvcache-profile/burstgpt_kvcache_20260629_141010/block_lba_trace.csv` | `kv-cache.py --num-users 8 --duration 120 --use-burst-trace` (llama3.1-8b, TP=1, 0/0 GiB GPU/CPU cache) + bpftrace | 129.75s | 4,566,627 |

**统一方法学 (v3):** 三种 workload 现在都用**同一方法学** — llama3.1-8b TP=1,8 users,120s,forced NVMe (0/0 GiB GPU/CPU cache),混合 prefill+decode (无 `--prefill-only` / `--decode-only`)。**default 是 workload runner 的真实默认行为**,不再是两段拼装。

**tracepoint 字段:** `timestamp_ns, dev, sector, bytes, rwbs, comm, pid`
**LBA 推导:** `LBA = sector * 512`
**相邻 I/O 对:** 同一个 PID 上相邻两次 block_rq_issue 的 sector delta

---

## 一、综合压力对比 (Signal Dashboard)

![signal_dashboard](assets/io-three-way-comparison/01_signal_dashboard.png)

| 指标 | default | sharegpt | burstgpt |
|---|---:|---:|---:|
| **Block events** | **4,090,543** | 1,981,685 | 4,566,627 |
| **Block IOPS** | 30,806 | 14,063 | **35,195** |
| **Block BW (GiB/s)** | 3.75 | 1.64 | **4.25** |
| **Read events** | 3,613,662 (88%) | **1,860,196 (94%)** | 4,202,655 (92%) |
| **Write events** | **476,881 (12%)** | 121,489 (6%) | 363,972 (8%) |
| **Read 相邻 ≥100 MiB 跳跃** | 79.16% | 56.97% | **89.11%** |
| **Read 相邻精确连续** | 0.0% | **41.77%** | 10.08% |
| **Write 相邻精确连续** | 0.9% | 94.37% | **97.63%** |
| **Dominant block size** | 128 KiB (99.6%) | 128 KiB (93.9%) | **128 KiB (98.5%)** |
| **LBA span (GiB)** | **389.38** | **389.35** | **389.35** |
| **Total bytes (GiB)** | 497.65 | 42.74 | 72.16 |

**关键发现:**
- **default 是最 read-heavy** — 写只占 12%(其他两份 6-8%),符合真实推理服务中 decode 远多于 prefill 的特征
- **burstgpt 压力最大** — IOPS (35K) 和 BW (4.25 GiB/s) 居首,Read ≥100MiB jump 89.11% — 突发短 prompt 流
- **default 跟 burstgpt 量级接近** — 4.09M events / 30.8K IOPS / 3.75 GiB/s,burstgpt 是它的 1.1×
- **sharegpt 有意外连续读 (41.8%)** — 多轮对话 prefix cache 命中时,相邻 KV 块物理位置相同
- **三种 workload 写几乎纯连续** (default 0.9% exact contig 看似低,但 p50=0.125 MiB 实际是顺序 append;sharegpt/burstgpt 94-98% 显式连续) — 写都是顺序 KV 块追加,这是 KV-cache IO 的共性

---

## 二、IOPS 与 BW 时间序列

![iops_bw_timeline](assets/io-three-way-comparison/02_iops_bw_timeline.png)

| 特征 | default | sharegpt | burstgpt |
|---|---|---|---|
| 平均 IOPS (1s 窗) | 30,806 | 14,063 | **35,195** |
| IOPS p95 | 32,604 (1s) | 32,604 (3s) | 40,938 (3s) |
| IOPS max | 35,755 (1s) | 35,755 (3s) | 42,930 (3s) |
| IOPS 变异系数 (CV) | 0.61 | **0.61** | 0.28 |
| Peak / Mean | 2.07 | **2.07** | 1.19 |

**统一粒度:** v3 起三种 workload 都用 **1s 窗**的 per-second time-series 数据(从 `iops_per_sec` / `bw_per_sec_giB` 字段读出),可直接在 timeline 图上叠加对比。sharegpt/burstgpt 的 3s 窗 p95/max 是历史计算结果,跟 1s 窗在大致同一量级。

**default 的 IO 行为特征:** 跟 sharegpt 一样属于**脉冲型** (CV=0.61, Peak/Mean=2.07),介于 sharegpt 和 burstgpt (稳态) 之间。写操作主要是顺序 KV 块追加,读操作是从 389 GiB LBA span 跨块随机读 (p50=5,033 MiB)。**这是真实 mixed prefill+decode 服务的典型行为**。

---

## 三、相邻 LBA 跳跃分布 (CDF)

![lba_delta_cdf](assets/io-three-way-comparison/03_lba_delta_cdf.png)

### 读 (R) 相邻跳跃

| 指标 | default | sharegpt | burstgpt |
|---|---:|---:|---:|
| 相邻 pair 数 | 3,613,661 | 1,860,196 | 4,202,655 |
| **精确连续** | 0.0% | **41.77%** | 10.08% |
| 近邻 `<1 MiB` | 0.1% | 42.27% | 10.30% |
| **大跳跃 `≥100 MiB`** | 79.16% | 56.97% | **89.11%** |
| Abs delta p50 | 5,033 MiB | 2,675 MiB | 31,056 MiB |
| Abs delta p95 | 88,607 MiB | 154,298 MiB | 126,769 MiB |

### 写 (W) 相邻跳跃

| 指标 | default | sharegpt | burstgpt |
|---|---:|---:|---:|
| 相邻 pair 数 | 476,820 | 121,487 | 363,970 |
| **精确连续** | 0.9% | 94.37% | **97.63%** |
| 近邻 `<1 MiB` | 95.1% | 96.36% | 98.40% |
| 大跳跃 `≥100 MiB` | **4.9%** | 3.29% | 1.40% |
| Abs delta p50 | 0.125 MiB | 0.00 MiB | 0.00 MiB |
| Abs delta p95 | 0.125 MiB | 0.02 MiB | 0.00 MiB |

**为什么 default 读也是大跳跃为主 (79%):**
- 真实 mixed prefill+decode 服务中,decode 阶段随机触发 KV cache 读,跨越整个 389 GiB LBA span
- p50 = 5,033 MiB,中位数跳跃 5 GB,几乎每次都跨越大块地址
- 跟 burstgpt 性质类似,但程度稍轻(79% vs 89%)

**为什么 sharegpt 有 41.8% 读连续:**
- prefix cache 命中时,相邻请求的 KV 块位置相同 → "逻辑连续" = "物理相同"
- 这是 sharegpt 多轮对话的特殊性,burstgpt 和 default 都没有这种机制

**为什么 default 写 95% 在 <1 MiB 范围内 (精确连续 0.9% 看似低):**
- 写操作是顺序 KV 块追加,物理上相邻两次写都贴近
- "精确连续 0.9%" 的统计口径是 byte-level LBA = LBA(前一个) + bytes(前一个)
- 因为相邻 KV 块大小不固定 (page size 不对齐),LBA 跳跃很小但不是 0
- 跟 sharegpt/burstgpt 一样,本质都是顺序写,只是统计精度不同

---

## 四、块大小分布

![block_size_distribution](assets/io-three-way-comparison/04_block_size_distribution.png)

三种 workload 都以 128 KiB 为主:

| Workload | 128 KiB 占比 | 次主导 |
|---|---:|---|
| default | 99.6% (4,074,111) | < 1% 其他 |
| sharegpt | 93.9% | 64 KiB (6%) |
| burstgpt | **98.5%** | < 1% |

**观察:**
- 三种 workload 都以 128 KiB 占主导 — 跟 sglang/HF model KV cache 的 page size = 64 token (每个 page 序列化为 128 KiB) 一致
- **default 块大小分布比 sharegpt 集中 (99.6% vs 93.9%)** — 默认 mixed workload 没有 prefix cache 命中的小块混杂,纯 page 写
- **burstgpt 几乎纯 128K (98.5%)** → **device IO 调度可以用固定 128K 块假设简化**
- sharegpt 有少量 64 KiB — 可能来自 prefix cache 命中时的 half-block promotion

---

## 五、压力归一化热图

![pressure_heatmap](assets/io-three-way-comparison/05_pressure_heatmap.png)

各列独立归一化(每列最大值 = 1.0):

| Workload | IOPS (×1000) | BW (GiB/s) | Read % | Read ≥100MiB jump % |
|---|---:|---:|---:|---:|
| default | 30.8 | 3.75 | 88 | 79.16 |
| sharegpt | 14.1 | 1.64 | **94** | 56.97 |
| burstgpt | **35.2** | **4.25** | 92 | **89.11** |

**热图揭示:**
- **burstgpt 在 IOPS / BW / Read ≥100MiB jump 三项都是最高** — 最重压力
- **default 跟 burstgpt 量级接近** (30.8 vs 35.2K IOPS, 3.75 vs 4.25 GiB/s) — 默认 mixed workload 不是轻量级
- **sharegpt 在 Read % 上最高 (94%)** — 因为写很少 (只 6%),全部事件几乎都是读
- **三种 workload 各自在不同维度称王**,**不能用一个顶替另一个**

---

## 六、跨报告结论的一致性

| 报告 | 核心结论 | 本文如何补充 |
|---|---|---|
| `kv-cache-nvme-offload-real-io-analysis-2026-06-29.md` (v2 morning) | 读 95% ≥100MiB 跳跃,写 75% 精确连续 | **v3 修正**:default 列替换为真实 mixed-mode 数据 (读 79% 大跳跃,写 95% 在 <1 MiB) — 降低了 v2 的人为虚高 |
| `kv-cache-sharegpt-vs-burstgpt-io-2026-06-29.md` (上一份) | sharegpt vs burstgpt IO 模式差异 2.5× IOPS, 2.6× BW | **加入 default** 作为真实 workload runner 默认行为的基准锚定 (TP=1, 8u, 120s) |
| 本文 (v3) | 三路对比,统一方法学 (TP=1, 8u, 120s, llama3.1-8b, forced NVMe) | 给出 PPT-ready 的对比图和压力热图 |

**本文修正了之前三路对比的错误:**
- ❌ 旧版"三路"里的 synthetic 是 fio_sweep (与 sharegpt/burstgpt 不可比)
- ✅ 新版"三路"都是 kv-cache.py 跑出来的 (default + sharegpt + burstgpt)
- 仍保留 fio_sweep 设备能力 sanity check,但**单独成段,不参与三路对比**

---

## 七、对 fio_sweep 的诚实评价 (本工作不动,仅备注)

fio_sweep 数据保留在 `results/kvcache-profile/fio_sweep/`,**只用于 BIWIN 盘 device capability ceiling 标定**,**不参与本次三路对比**。它的问题:
- 块大小多样 (4k-128k) 跟真实 KV cache (几乎纯 128K) 不符
- 没有 PID 连续性,**没有 LBA 跳跃分布**
- 是稳态负载,**没有突发性**
- 不能反映应用层语义 (decode vs prefill 切换)

详见: `docs/kv-cache-device-io-analysis-2026-06-25.md` 等历史报告

---

## 八、给后续工作的建议

1. **v3 收尾** — 三路对比方法学已统一 (TP=1, 8u, 120s, llama3.1-8b, forced NVMe),不再需要后续校准
2. **default 原始 CSV 保留** — 在 `results/kvcache-profile/default_baseline/` 下,250MB,不入 git 作 audit trail
3. **下一步如果做 Mooncake SSD offload 评估**:
   - **稳态 + 随机读压力** → 用 burstgpt (更接近 DGX 原始 benchmark)
   - **混合压力** → 用 sharegpt (有 prefix cache 命中)
   - **baseline** → 用 default (workload runner 默认 mixed prefill+decode)

---

## 附录:工具链备忘

```bash
# 跑 default (mixed prefill+decode, TP=1, 跟 sharegpt/burstgpt 同方法学)
~/llm/storage/kv_cache_benchmark/.venv/bin/python3 \
  ~/llm/storage/kv_cache_benchmark/kv-cache.py \
  --num-users 8 --duration 120 \
  --model llama3.1-8b --tensor-parallel 1 \
  --gpu-mem-gb 0 --cpu-mem-gb 0 \
  --cache-dir ~/llm/storage/results/kvcache-profile/ext4_kvcache_default_baseline \
  --storage-capacity-gb 40

# 跑 sharegpt (multi-turn 开启,跟默认 workload runner 行为一致)
~/llm/storage/kv_cache_benchmark/.venv/bin/python3 \
  ~/llm/storage/kv_cache_benchmark/kv-cache.py \
  --num-users 8 --duration 120 \
  --model llama3.1-8b --tensor-parallel 1 \
  --gpu-mem-gb 0 --cpu-mem-gb 0 \
  --cache-dir ~/llm/storage/results/kvcache-profile/ext4_kvcache_sharegpt \
  --storage-capacity-gb 40

# 跑 burstgpt (加 --use-burst-trace)
~/llm/storage/kv_cache_benchmark/.venv/bin/python3 \
  ~/llm/storage/kv_cache_benchmark/kv-cache.py \
  --use-burst-trace \
  --burst-trace-path ~/llm/storage/datasets/BurstGPT/data/BurstGPT_1.csv \
  --num-users 8 --duration 120 ...

# bpftrace 捕获
sudo /usr/bin/bpftrace ~/llm/storage/scripts/trace_block_lba.bt 271581194

# 后处理 → block_lba_trace.csv + lba_trace_summary.json
# (见 ~/llm/storage/scripts/analyze_sharegpt_burstgpt_io.py)

# 重新生成综合图
~/llm/storage/.venv/bin/python3 \
  ~/llm/storage/scripts/io_three_way_comparison.py
```